import http.cookiejar
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8088/api/v1"
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
TOK = None
CSRF = None

CHART_IDS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]


def req(m, p, d=None, auth=False):
    h = {"Content-Type": "application/json"}
    if auth:
        h["Authorization"] = "Bearer " + TOK
        if CSRF:
            h["X-CSRFToken"] = CSRF
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None, headers=h, method=m)
    try:
        with OP.open(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def main():
    global TOK, CSRF
    _, data = req("POST", "/security/login", {"username": "admin", "password": "admin", "provider": "db", "refresh": True})
    TOK = data["access_token"]
    _, c = req("GET", "/security/csrf_token/", auth=True)
    CSRF = c.get("result")

    ds_cache = {}

    def get_ds(dsid):
        if dsid in ds_cache:
            return ds_cache[dsid]
        _, d = req("GET", f"/dataset/{dsid}", auth=True)
        ds = d.get("result", {})
        ds_cache[dsid] = ds
        return ds

    for cid in CHART_IDS:
        _, ch = req("GET", f"/chart/{cid}", auth=True)
        ch = ch.get("result", {})
        name = ch.get("slice_name")
        params = json.loads(ch.get("params") or "{}")
        dsid = ch.get("datasource_id")
        datasource = {"id": dsid, "type": "table"}
        queries0 = dict(params)
        queries0.pop("datasource", None)
        payload = {"datasource": datasource, "queries": [queries0]}
        code, res = req("POST", "/chart/data", payload, auth=True)
        ok = code in (200, 201) and not res.get("errors") and bool(res.get("result"))
        detail = ""
        if not ok:
            errs = res.get("errors") or []
            if errs:
                detail = str(errs[0].get("message", errs[0]))[:180]
            else:
                detail = f"code={code} {json.dumps(res)[:180]}"
        print(f"{'OK  ' if ok else 'FAIL'} id={cid} {name}  {detail}")


if __name__ == "__main__":
    main()