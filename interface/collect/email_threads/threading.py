from .abort import ParsingAbort
from .guards import MAX_REFERENCES

def build_threads(messages: list[dict]) -> dict[str, str]:
    parent = {}
    def find(x):
        if x not in parent: parent[x] = x
        if parent[x] != x: parent[x] = find(parent[x])
        return parent[x]
    def union(x, y):
        if x not in parent: parent[x] = x
        if y not in parent: parent[y] = y
        root_x, root_y = find(x), find(y)
        if root_x != root_y:
            if root_x < root_y: parent[root_y] = root_x
            else: parent[root_x] = root_y
                
    for msg in messages:
        mid = msg.get("message_id")
        if not mid: continue
        find(mid)
        if in_reply := msg.get("in_reply_to"):
            union(mid, in_reply)
        refs = msg.get("references", [])
        if len(refs) > MAX_REFERENCES:
            raise ParsingAbort("REFERENCES_CHAIN")
        for ref in refs:
            union(mid, ref)
    return {mid: find(mid) for mid in parent}
