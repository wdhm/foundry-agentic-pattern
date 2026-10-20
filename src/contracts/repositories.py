"""Canonical Azure Repos references shared by read guards and evidence checks."""

from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit


@dataclass(frozen=True)
class AzureRepository:
    organization: str
    project: str
    repository: str


def azure_repository(value: str) -> AzureRepository:
    url = urlsplit(value)
    parts = url.path.strip("/").split("/")
    if (
        url.scheme != "https" or url.netloc != "dev.azure.com" or url.query or url.fragment
        or len(parts) != 4 or parts[2] != "_git"
    ):
        raise ValueError("Azure Repos requires https://dev.azure.com/<organization>/<project>/_git/<repository>.")
    names = [unquote(parts[index]) for index in (0, 1, 3)]
    if any(
        not name or name != name.strip() or name in {".", ".."} or any(c in name for c in "/\\%?#")
        for name in names
    ):
        raise ValueError("Azure Repos references must have unambiguous organization, project and repository names.")
    return AzureRepository(*names)


def azure_file_uri(repository: AzureRepository, path: str, commit: str) -> str:
    prefix = "/".join(quote(value, safe="") for value in (
        repository.organization, repository.project, "_apis", "git", "repositories", repository.repository, "items"
    ))
    query = urlencode({
        "path": path,
        "versionDescriptor.version": commit,
        "versionDescriptor.versionType": "Commit",
    })
    return f"https://dev.azure.com/{prefix}?{query}"


def matches_azure_file(uri: str, repository: AzureRepository, path: str, commit: str) -> bool:
    actual, expected = urlsplit(uri), urlsplit(azure_file_uri(repository, path, commit))
    query = parse_qs(actual.query, keep_blank_values=True)
    required = parse_qs(expected.query)
    return (
        actual.scheme == expected.scheme and actual.netloc == expected.netloc
        and actual.path == expected.path and not actual.fragment
        and all(query.get(key) == value for key, value in required.items())
        and set(query).issubset({*required, "api-version"})
        and ("api-version" not in query or len(query["api-version"]) == 1)
    )
