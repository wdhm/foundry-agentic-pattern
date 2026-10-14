# Slides: PDF and SharePoint document sources (P2, [#48](https://github.com/wdhm/foundry-agentic-pattern/issues/48))

Slot: 11:03–11:10 in the [agenda](../agenda.md). This topic is slides only ([ADR 0014](../../adr/0014-infrastructure-scope.md)).

---

## Slide: Index documents, call live for exact evidence

**Today:** the documentation standard and the ADRs sit in **Foundry IQ** (search index knowledge source, see the [Foundry IQ guide](../foundry-iq-guide.md)). Code, the wiki and work items are **live tool calls** at an exact version.

**Next:** add design documents, specs and vendor PDFs as more **knowledge sources** in the same knowledge base.

| Knowledge source | Type | Fits |
|---|---|---|
| Azure Blob | Indexed | PDFs in a storage container; the indexer cracks the documents |
| Indexed SharePoint (preview) | Indexed | A SharePoint site crawled on a schedule |
| Remote SharePoint (preview) | Remote | Queried live through the Copilot Retrieval API, **on behalf of the user** |
| File (preview) | Indexed | A few files uploaded directly, for demos |

**Index or call live?**

| | Indexed knowledge source | Live tool call (ADO / GitHub MCP) |
|---|---|---|
| Best for | Stable reference material: standards, specs, PDFs | Things that change with the code: files, wiki pages, work items |
| Evidence version | Indexed snapshot; store URL + ETag/hash at ingestion | Exact commit, blob or revision at call time |
| Freshness | Indexer schedule | Always current |
| Permissions | Agent/search identity, or permission-trimmed (remote SharePoint) | The agent identity's rights on the source |
| Cost and latency | Ingestion cost; fast semantic search over many documents | Cost per call; precise but narrow |

> **Speaker notes:** The rule from our evidence contract still holds: every claim cites a source at an exact version. Indexing works when the document is stable and you record its version. When you need proof of what the system does right now, call the source live. Remote SharePoint keeps the user's permissions, but each user needs a Microsoft 365 Copilot licence or pay-as-you-go Retrieval API. We used a search index source in the MVP because tenant policy forced storage public access off, so Blob would have needed private endpoints.

---

## References

- [What is a knowledge source?](https://learn.microsoft.com/azure/search/agentic-knowledge-source-overview)
- [What is Foundry IQ?](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq)
- [Blob knowledge source](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-blob)
- [Indexed SharePoint knowledge source (preview)](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-sharepoint-indexed)
- [Remote SharePoint knowledge source (preview)](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-sharepoint-remote)
- [Information retrieval: extend with Foundry IQ and Work IQ](https://learn.microsoft.com/azure/architecture/ai-ml/guide/rag/rag-information-retrieval#extend-retrieval-by-using-foundry-iq-and-work-iq)
