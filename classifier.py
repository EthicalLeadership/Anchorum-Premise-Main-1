import hashlib, json, os, re, subprocess, urllib.request

class Cache:
    def __init__(self): self._d = {}
    def get(self, k): return self._d.get(k)
    def put(self, k, v): self._d[k] = v

def _stub(prompt, sentence):
    return "NO"

def _anthropic(prompt, sentence):
    import anthropic
    c = anthropic.Anthropic()
    r = c.messages.create(
        model=os.environ.get("CLF_MODEL", "claude-3-5-haiku-latest"),
        max_tokens=4, temperature=0.0,
        system=prompt,
        messages=[{"role": "user", "content": sentence}],
    )
    return r.content[0].text

def _openai(prompt, sentence):
    import openai
    c = openai.OpenAI()
    r = c.chat.completions.create(
        model=os.environ.get("CLF_MODEL", "gpt-4o-mini"),
        temperature=0.0, max_tokens=4,
        messages=[{"role": "system", "content": prompt},
                  {"role": "user", "content": sentence}],
    )
    return r.choices[0].message.content

def _ollama(prompt, sentence):
    body = json.dumps({
        "model": os.environ.get("CLF_MODEL", "llama3.1:8b"),
        "prompt": prompt + "\n\nSentence: " + sentence,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate"),
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["response"]

def _command(cmd):
    def fn(prompt, sentence):
        r = subprocess.run(cmd, input=prompt + "\n\nSentence: " + sentence,
                           capture_output=True, text=True, shell=True, timeout=180)
        return r.stdout
    return fn

def make_backend(name):
    if name == "stub": return _stub
    if name == "anthropic": return _anthropic
    if name == "openai": return _openai
    if name == "ollama": return _ollama
    if name.startswith("command:"): return _command(name[len("command:"):])
    raise SystemExit(f"unknown backend: {name}")

def parse_yes_no(raw):
    s = raw.strip().upper()
    m = re.match(r"\s*(YES|NO)\b", s)
    if m: return m.group(1)
    hits = re.findall(r"\b(YES|NO)\b", s)
    if len(set(hits)) == 1: return hits[0]
    return "NO"

class Classifier:
    def __init__(self, prompt, backend):
        self.prompt = prompt
        self.backend = backend
        self.cache = Cache()
    def classify(self, sentence):
        key = hashlib.sha256((self.prompt + "\x00" + sentence).encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is not None: return hit
        raw = self.backend(self.prompt, sentence)
        result = parse_yes_no(raw) == "YES"
        self.cache.put(key, result)
        return result
