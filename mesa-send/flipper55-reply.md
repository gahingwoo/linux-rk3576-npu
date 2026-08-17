@tomeuv Sorry, that was too long and mixed several things. One question, about
the branch.

rkt_ml_subgraph_invoke submits one job per operation when the weights fit the
CBUF and one per task when they do not, which comes out as 27 jobs and 34 tasks
for MobileNet. My branch also has rkt_pack_graph_regcmd, which packs the whole
graph into a single PC job with task_number set to the total, the way the
vendor dispatches. It was gated off because it used to stall, and that gate
turned out to be stale. With it on the same graph is 1 job and the same 34
tasks, 1000 of 1001 channels either way, three runs, no stall.

Would you want that as the default, or one job per operation kept as it is?
