"""Operator-owned Teams scope; never populated from card values."""

import os
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from microsoft_agents.activity import Activity
from pydantic import Field, model_validator

from contracts.models import ContractModel, NonBlank


class SharedReviewScope(ContractModel):
    tenant_id: UUID
    team_id: NonBlank
    channel_id: NonBlank
    conversation_id: NonBlank
    thread_id: NonBlank
    team_aad_group_id: UUID | None = None


class TeamsChannelPolicy(ContractModel):
    tenant_id: UUID
    team_id: NonBlank | None = None
    team_aad_group_id: UUID | None = None
    channel_id: NonBlank
    reviewer_mode: Literal["allowlist", "channel_members"] = "allowlist"
    reviewer_aad_ids: Annotated[list[UUID], Field(max_length=50)] = Field(default_factory=list)
    channel_type: Literal["standard"] = "standard"

    @model_validator(mode="after")
    def unique_reviewers(self) -> Self:
        if self.team_id is None and self.team_aad_group_id is None:
            raise ValueError("Pin either the Teams internal team ID or the team's Entra group ID.")
        if len(set(self.reviewer_aad_ids)) != len(self.reviewer_aad_ids):
            raise ValueError("Channel reviewer IDs must be unique.")
        if self.reviewer_mode == "allowlist" and not self.reviewer_aad_ids:
            raise ValueError("Allowlist mode requires at least one reviewer.")
        if self.reviewer_mode == "channel_members" and self.reviewer_aad_ids:
            raise ValueError("Channel membership mode must not also specify an allowlist.")
        return self

    @classmethod
    def from_environment(cls) -> Self | None:
        if os.environ.get("DOCUMENTATION_ENABLE_CHANNEL_REVIEWS") != "true":
            return None
        path = os.environ.get("DOCUMENTATION_TEAMS_CHANNEL_POLICY")
        if not path:
            raise ValueError("Channel reviews require DOCUMENTATION_TEAMS_CHANNEL_POLICY.")
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def require_scope(self, scope: SharedReviewScope) -> None:
        if scope.tenant_id != self.tenant_id:
            raise ValueError("This review is outside the configured Teams tenant.")
        if scope.channel_id != self.channel_id:
            raise ValueError("This review is outside the configured Teams channel.")
        if self.team_id is not None and scope.team_id != self.team_id:
            raise ValueError("This review is outside the configured Teams internal team.")
        if self.team_aad_group_id is not None and scope.team_aad_group_id != self.team_aad_group_id:
            raise ValueError("This review is outside the configured Teams group or its group ID could not be verified.")

    def require_reviewer(self, aad_id: UUID) -> None:
        if self.reviewer_mode == "allowlist" and aad_id not in self.reviewer_aad_ids:
            raise ValueError("You can view and discuss this review, but are not an authorized channel reviewer.")

    def show_decisions(self, aad_id: UUID) -> bool:
        # UI eligibility only; channel_members requires a fresh roster lookup.
        return self.reviewer_mode == "channel_members" or aad_id in self.reviewer_aad_ids

    def scope(self, activity: Activity) -> SharedReviewScope:
        data = activity.channel_data
        conversation = activity.conversation
        if not isinstance(data, dict) or conversation is None or conversation.conversation_type != "channel":
            raise ValueError("A verified Teams channel conversation is required.")
        values = []
        for key in ("tenant", "team", "channel"):
            item = data.get(key)
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("Teams channel activity is missing tenant/team/channel identity.")
            values.append(item["id"])
        conversation_id, _, encoded_thread = (conversation.id or "").partition(";messageid=")
        # Card callbacks can reply to the card message rather than the root post.
        # Teams' thread-bearing conversation ID remains the root identity.
        thread_id = encoded_thread or activity.reply_to_id or activity.id
        scope = SharedReviewScope(
            tenant_id=UUID(values[0]), team_id=values[1], channel_id=values[2],
            conversation_id=conversation_id, thread_id=thread_id or "",
            team_aad_group_id=data["team"].get("aadGroupId"),
        )
        self.require_scope(scope)
        return scope
