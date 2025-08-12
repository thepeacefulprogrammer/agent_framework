from types import SimpleNamespace

context = SimpleNamespace()

def reset():
    keep = ("events", "running")
    d = context.__dict__
    for k in list(d):
        if k not in keep:
            del d[k]


