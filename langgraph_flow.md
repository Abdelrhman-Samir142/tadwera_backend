`mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	router(router)
	instant_response(instant_response)
	followup(followup)
	vector_retrieval(vector_retrieval)
	sql_retrieval(sql_retrieval)
	rrf_fusion(rrf_fusion)
	synthesis(synthesis)
	__end__([<p>__end__</p>]):::last
	__start__ --> router;
	router -.-> followup;
	router -.-> instant_response;
	router -.-> sql_retrieval;
	router -.-> vector_retrieval;
	rrf_fusion --> synthesis;
	sql_retrieval --> rrf_fusion;
	synthesis -. &nbsp;end&nbsp; .-> __end__;
	vector_retrieval --> rrf_fusion;
	followup --> __end__;
	instant_response --> __end__;
	synthesis -. &nbsp;retry&nbsp; .-> synthesis;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

`