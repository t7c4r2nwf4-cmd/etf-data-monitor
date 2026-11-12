"""Free public-data collector for 588940, 513650, SPX. No broker access.
All forecasts here are independent MACHINE BASELINES, NOT ChatGPT forecasts.
Never use data with unverifiable quote timestamps to pretend a live trade.
"""
from __future__ import annotations

import csv
import html
import io
import json
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import pandas as pd
import requests
import yfinance as yf

CN = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 ETF-Research/1.0"})
CODES = ("588940", "513650")


def num(value):
    try:
        n = float(str(value).replace(",", ""))
        return n if 0 < n < 1e10 else None
    except (TypeError, ValueError):
        return None


def calendar(market):
    # Fails closed if the library has no official trading calendar for the date.
    return xc.get_calendar(market)


def is_trading_day(now):
    try:
        return bool(calendar("XSHG").is_session(pd.Timestamp(now.date())))
    except (ValueError, KeyError, OverflowError):
        return False


def next_cn_day(now):
    c = calendar("XSHG")
    return str(c.date_to_session(pd.Timestamp(now.date() + timedelta(days=1)), direction="next").date())


def next_us_day(now):
    n = now.astimezone(NY)
    c = calendar("XNYS")
    today = pd.Timestamp(n.date())
    if c.is_session(today) and now.astimezone(UTC) < c.session_close(today).to_pydatetime():
        return str(today.date())
    return str(c.date_to_session(today + pd.Timedelta(days=1), direction="next").date())


def slot(now):
    t = now.time()
    if time(8, 35) <= t < time(9): return "09"
    if time(13, 35) <= t < time(14): return "14"
    if time(14, 20) <= t < time(14, 35): return "1430"
    if time(14, 40) <= t < time(15): return "1445"
    return "other"


def ledger(name):
    p = DATA / name
    if not p.exists(): return []
    result = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip(): result.append(json.loads(line))
    return result


def append_unique(name, row):
    if any(x.get("id") == row["id"] for x in ledger(name)):
        return False
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / name).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def parse_quote_time(value):
    try:
        s = str(value)
        if s.isdigit() and len(s) == 14:
            return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=CN)
        if s.isdigit() and len(s) in (10, 13):
            return datetime.fromtimestamp(int(s) / (1000 if len(s) == 13 else 1), CN)
    except (ValueError, OverflowError):
        pass
    return None


def eastmoney(code):
    response = SESSION.get("https://push2.eastmoney.com/api/qt/stock/get",
       params={"secid": "1." + code, "fltt": "2",
               "fields": "f2,f5,f6,f18,f124,f441"},
       timeout=12)
    response.raise_for_status()
    row = response.json().get("data") or {}
    price, prev = num(row.get("f2")), num(row.get("f18"))
    ts = parse_quote_time(row.get("f124"))
    if not (price and prev and ts):
        raise ValueError("missing price, prior close or original timestamp")
    return dict(price=price, prev_close=prev, quote_time=ts.isoformat(),
                source="eastmoney_push2", volume=num(row.get("f5")),
                turnover_cny=num(row.get("f6")))


def tencent(code):
    response = SESSION.get("https://qt.gtimg.cn/q=sh" + code, timeout=12)
    response.raise_for_status()
    raw = response.content.decode("gbk", "replace")
    cells = raw.split('="', 1)[1].split('"', 1)[0].split("~")
    if len(cells) < 32 or cells[2] != code:
        raise ValueError("incomplete Tencent quote")
    price, prev, ts = num(cells[3]), num(cells[4]), parse_quote_time(cells[30])
    if not (price and prev and ts):
        raise ValueError("Tencent quote missing price, prior close or timestamp")
    return dict(price=price, prev_close=prev, quote_time=ts.isoformat(),
                source="tencent_fallback", volume=num(cells[6]), turnover_cny=None)


def etf(code, now):
    errors = []
    best = None
    for source in (eastmoney, tencent):
        try:
            row = source(code)
            age = round((now - datetime.fromisoformat(row["quote_time"])).total_seconds()/60, 2)
            trading = time(9, 30) <= now.time() <= time(15, 0)
            fresh = (0 <= age <= 6) if trading else (0 <= age <= 60)
            row.update(code=code, pct_change=round((row["price"] / row["prev_close"] - 1) * 100, 3),
                       age_minutes=age, is_fresh=fresh, state="fresh" if fresh else "stale",
                       # f441 is not proven to be a trustworthy IOPV on this product.
                       iopv=None, premium_pct=None)
            if fresh: return row, errors
            if best is None: best = row
            errors.append(source.__name__ + ": quote is stale")
        except Exception as e:
            errors.append(source.__name__ + ": " + str(e)[:130])
    return best, errors


def etf_daily(code):
    r = SESSION.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
       params={"secid": "1." + code, "klt": "101", "fqt": "0", "lmt": "20",
               "fields1": "f1,f2,f3,f4,f5,f6",
               "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"},
       timeout=12)
    r.raise_for_status()
    entries = (r.json().get("data") or {}).get("klines") or []
    bars = []
    for entry in entries:
        fields = entry.split(",")
        if len(fields) >= 3 and num(fields[2]):
            bars.append({"date":fields[0], "close":num(fields[2])})
    if len(bars) < 2: raise ValueError("insufficient daily bars")
    return bars


def yahoo(symbol, period="10d", interval="1d"):
    d = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if d is None or d.empty: raise ValueError("no Yahoo data")
    d = d.dropna(subset=["Close"])
    last = d.iloc[-1]
    ts = d.index[-1].to_pydatetime()
    if ts.tzinfo is None: ts = ts.replace(tzinfo=UTC)
    out = dict(symbol=symbol, price=round(float(last["Close"]), 5),
               bar_time=ts.isoformat(), source="yfinance_unofficial",
               bar_interval=interval)
    if len(d) >= 2:
        prev = float(d.iloc[-2]["Close"])
        out["previous_bar_close"] = round(prev, 5)
        out["change_vs_prev_bar_pct"] = round((float(last["Close"])/prev - 1)*100, 3)
    return out


def official_spx(now):
    # Ignore in-progress daily bars and settle only after actual NYSE session close.
    d = yf.Ticker("^GSPC").history(period="15d", interval="1d", auto_adjust=False)
    if d is None or len(d) < 2: raise ValueError("SPX history unavailable")
    c = calendar("XNYS")
    completed = []
    for idx, rec in d.iterrows():
        day = pd.Timestamp(idx.date())
        if not c.is_session(day): continue
        if now.astimezone(UTC) >= c.session_close(day).to_pydatetime() + timedelta(minutes=40):
            if pd.notna(rec["Close"]): completed.append((str(day.date()), float(rec["Close"])))
    if len(completed) < 2: raise ValueError("no two completed SPX sessions")
    a, b = completed[-2:]
    return {"source":"yfinance_post_close_reference",
            "bar_time":b[0], "price":round(b[1], 5),
            "previous_bar_close":round(a[1], 5),
            "change_vs_prev_bar_pct":round((b[1]/a[1] - 1)*100, 3)}


def us_data(now):
    results, errors = {}, []
    for key, symbol, period, interval in [
        ("es", "ES=F", "2d", "5m"),
        ("vix", "^VIX", "2d", "5m"),
        ("usdcny", "CNY=X", "2d", "5m"),
        ("tnx", "^TNX", "2d", "5m"),
        ("semis", "^SOX", "10d", "1d"),
        ("es_daily", "ES=F", "10d", "1d"),
    ]:
        try:
            q = yahoo(symbol, period, interval)
            age = (now - datetime.fromisoformat(q["bar_time"])).total_seconds()/60
            q["age_minutes"] = round(age, 1)
            q["is_fresh"] = 0 <= age <= (30 if interval == "5m" else 2500)
            results[key] = q
        except Exception as e:
            errors.append(key + ": " + str(e)[:130])
    try: results["spx"] = official_spx(now)
    except Exception as e: errors.append("SPX: " + str(e)[:130])
    return results, errors


def collect(now):
    snapshot = {"schema":"etf-feed-v2", "collected_at":now.isoformat(),
                "slot":slot(now), "quotes":{}, "daily":{}, "us":{},
                "errors":[], "warnings":["PUBLIC QUOTES MAY BE DELAYED",
                 "Unverified IOPV is intentionally null; never infer current premium."]}
    for code in CODES:
        q, errs = etf(code, now)
        if q: snapshot["quotes"][code] = q
        snapshot["errors"] += [code + ": " + x for x in errs]
        try: snapshot["daily"][code] = etf_daily(code)
        except Exception as e: snapshot["errors"].append(code + " daily: " + str(e)[:130])
    snapshot["us"], errs = us_data(now)
    snapshot["errors"] += errs
    return snapshot


def heuristic(score):
    # NOT a calibrated probability; machine-only directional reference.
    if score is None: return None
    return {"direction":"涨" if score >= 0 else "跌",
            "strength_unvalidated_pct":round(min(62, 50+abs(score)*3)),
            "model":"unvalidated_momentum_baseline_v2"}


def predict(now, snap):
    kind = slot(now)
    if kind not in ("09", "14"): return []
    d = now.date().isoformat()
    semis = (snap["us"].get("semis") or {}).get("change_vs_prev_bar_pct")
    es = snap["us"].get("es_daily") or {}
    eschg = es.get("change_vs_prev_bar_pct") if es.get("is_fresh") else None
    etf_q = snap["quotes"].get("588940") or {}
    change = etf_q.get("pct_change") if etf_q.get("is_fresh") else None
    sp = heuristic(eschg)
    if kind == "09":
        et = heuristic(0.65*semis + 0.35*eschg) if semis is not None and eschg is not None else None
        etday = d
    else:
        et = heuristic(0.65*change + 0.35*semis) if change is not None and semis is not None else None
        etday = next_cn_day(now)
    out = []
    for market, target, signal in (("SPX", next_us_day(now), sp), ("588940", etday, et)):
        if signal is None: continue
        row = {"id":d+"-"+kind+"-"+market, "market":market,
               "slot":kind, "created_at":now.isoformat(),
               "target_session":target, "source":"MACHINE_NOT_CHATGPT", **signal}
        if append_unique("predictions.jsonl", row): out.append(row)
    return out


def settle(now, snap):
    past = {x["prediction_id"] for x in ledger("outcomes.jsonl")}
    etf_bars = {x["date"]:x["close"] for x in snap["daily"].get("588940", [])}
    spx = snap["us"].get("spx") or {}
    out = []
    for p in ledger("predictions.jsonl"):
        if p["id"] in past: continue
        target = p["target_session"]
        actual = None
        source = None
        if p["market"] == "588940":
            if now.date().isoformat() > target or (
                    now.date().isoformat() == target and now.time() >= time(16)):
                before = [d for d in etf_bars if d < target]
                if before and target in etf_bars and etf_bars[target] != etf_bars[max(before)]:
                    actual = "涨" if etf_bars[target] > etf_bars[max(before)] else "跌"
                    source = "eastmoney_dated_daily_kline"
        elif p["market"] == "SPX" and spx.get("bar_time") == target:
            change = spx.get("change_vs_prev_bar_pct")
            if change is not None and change != 0:
                actual = "涨" if change > 0 else "跌"
                source = spx.get("source")
        if actual is not None:
            row = {"id":"settle-"+p["id"], "prediction_id":p["id"],
                   "market":p["market"], "slot":p["slot"],
                   "target_session":target, "prediction":p["direction"],
                   "actual":actual, "correct":actual==p["direction"],
                   "settled_at":now.isoformat(), "source":source}
            if append_unique("outcomes.jsonl", row): out.append(row)
    return out


def stats():
    out = ledger("outcomes.jsonl")
    forecasts = ledger("predictions.jsonl")
    result = {}
    for market in ("SPX", "588940"):
        for kind in ("09", "14"):
            rows = [x for x in out if x["market"]==market and x["slot"]==kind]
            n, wins = len(rows), sum(x["correct"] for x in rows)
            result[market+"_"+kind] = {"settled":n, "wins":wins, "losses":n-wins,
                "accuracy_pct":round(wins/n*100, 1) if n else None,
                "locked":sum(x["market"]==market and x["slot"]==kind for x in forecasts)}
    # No confirmed live IOPV = no pretend simulations, and no imported ChatGPT history.
    result["paper_t"] = {"closed":0,"wins":0,"losses":0,"accuracy_pct":None,
                        "source":"no_verified_iopv_no_simulated_fills"}
    result["legacy_chatgpt_history"]="NOT_IMPORTED_NOT_OVERWRITTEN"
    return result


def render(s):
    esc = lambda x: html.escape(str(x))
    def cell(code):
        q = s["quotes"].get(code)
        if not q: return "<section><h2>"+code+"</h2><p>暂无行情</p></section>"
        return ("<section><h2>"+code+"</h2><strong>"+esc(q["price"])+
                " 元</strong><p>涨跌 "+esc(q["pct_change"])+
                "% | 价格时间 "+esc(q["quote_time"])+
                "</p><p>来源 "+esc(q["source"])+
                " | 新鲜度 "+("近期" if q["is_fresh"] else "过期")+
                "</p><p>IOPV：未核验；溢价：不可计算</p></section>")
    market = "".join("<p>"+esc(k)+"： "+esc(v.get("price","缺失"))+" | "+esc(v.get("bar_time",""))+"</p>"
                     for k,v in s["us"].items())
    errors = "".join("<li>"+esc(e)+"</li>" for e in s["errors"][:15])
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>ETF免费行情诊断</title><style>body{font-family:system-ui,sans-serif;"
            "max-width:780px;margin:24px auto;padding:0 15px;color:#182439}"
            "section{padding:16px;border:1px solid #ddd;border-radius:12px;margin:14px 0}"
            "strong{font-size:28px}small{color:#667}</style><h1>ETF / SPX 行情监控</h1>"
            "<small>采集于 "+esc(s["collected_at"])+"（北京时间）</small>"
            +cell("588940")+cell("513650")+
            "<section><h2>美股/宏观</h2>"+market+"</section>"
            "<section><h2>机器预测（非ChatGPT旧记录）</h2><pre>"
            +esc(json.dumps(s["stats"],ensure_ascii=False,indent=2))+
            "</pre></section><section><h2>故障诊断</h2><ul>"+errors+
            "</ul></section><a href='latest.json'>原始 JSON 数据</a>"
            "<p>公开行情可能延迟；未核验 IOPV 不计算溢价，不凭空记录 T 成交。</p></html>")


def run(now=None, reader=collect):
    now = now or datetime.now(CN)
    if not is_trading_day(now):
        print("Exchange closed or calendar unavailable; no report.")
        return None
    s = reader(now)
    s["new_predictions"] = predict(now, s)
    s["new_settlements"] = settle(now, s)
    s["stats"] = stats()
    s["health"] = {"etf_588940_fresh":bool((s["quotes"].get("588940") or {}).get("is_fresh")),
                   "etf_513650_fresh":bool((s["quotes"].get("513650") or {}).get("is_fresh")),
                   "spx_close_available":bool(s["us"].get("spx")),
                   "es_available":bool(s["us"].get("es")),
                   "verified_iopv_available":False}
    DATA.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DATA/"snapshots").mkdir(parents=True, exist_ok=True)
    filename = now.strftime("%Y-%m-%dT%H-%M-%S%z") + ".json"
    (DATA/"snapshots"/filename).write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")
    (DOCS/"latest.json").write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")
    (DOCS/"index.html").write_text(render(s),encoding="utf-8")
    print("Collected",s["collected_at"],"quotes",list(s["quotes"]),
          "us",list(s["us"]),"errors",len(s["errors"]))
    return s


if __name__ == "__main__":
    run()
