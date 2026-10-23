This project was built with the microsoft-foundry skill. Before working on or
answering questions about foundry agents, read the microsoft-foundry skill first.

Keep assessment mode read-only. The #1 approval spike is a separate experiment
with a dummy state receipt, not authorization to enable real wiki writes.

Conversational chat is also read-only and separately opt-in. Reuse the reviewed
source guards; chat history or natural-language agreement never authorizes a
proposal, source-scope expansion or write. Keep structured and native approval
inputs out of the conversational model.

Shared channel reviews are separately opt-in. Require the exact configured
tenant/team/channel/thread and current reviewer rule on every decision. Membership
mode requires a live sender-roster lookup and rechecks before the write claim.
Use the separate shared approval store; never spoof platform identity, copy a
personal approval into a channel, or expose channel approvals through Responses.

The #15 approval mode is separately opt-in and requires an operator-reviewed
tool/target policy. Never broaden assessment tools or automatically retry a
claimed external write. See TOOL_APPROVAL.md for uncertainty and persistence limits.
