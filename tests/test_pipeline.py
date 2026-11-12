"""Offline tests. Synthetic data only, not a claim about live exchange prices."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main

CN = ZoneInfo("Asia/Shanghai")


def sample(now):
    ts=(now-timedelta(minutes=1)).isoformat()
    return {
        "schema":"etf-feed-v2","collected_at":now.isoformat(),
        "slot":main.slot(now),
        "quotes":{
           "588940":{"code":"588940","price":0.65,"prev_close":0.645,
                     "pct_change":0.775,"quote_time":ts,"is_fresh":True,"source":"mock"},
           "513650":{"code":"513650","price":1.95,"prev_close":1.94,
                     "pct_change":0.515,"quote_time":ts,"is_fresh":True,
                     "iopv":None,"premium_pct":None,"source":"mock"}
        },
        "daily":{"588940":[{"date":"2026-11-11","close":0.64},
                            {"date":"2026-11-12","close":0.65}]},
        "us":{"es_daily":{"is_fresh":True,"change_vs_prev_bar_pct":0.2},
              "semis":{"change_vs_prev_bar_pct":0.3},
              "spx":{"bar_time":"2026-11-11","price":7100,
                     "change_vs_prev_bar_pct":0.6,"source":"mock"}},
        "errors":[],"warnings":[]
    }


def test_day_and_slots():
    a=datetime(2026,11,12,8,45,tzinfo=CN)
    assert main.is_trading_day(a)
    assert main.slot(a)=="09"
    assert main.slot(a.replace(hour=13, minute=45))=="14"
    assert main.next_cn_day(a)=="2026-11-13"
    assert main.next_us_day(a)=="2026-11-12"
    assert not main.is_trading_day(a.replace(day=14))


def test_immutable_09_14_ledgers(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DATA",tmp_path)
    a=datetime(2026,11,12,8,45,tzinfo=CN)
    first=main.predict(a,sample(a))
    assert len(first)==2
    assert main.predict(a,sample(a))==[]
    assert main.predict(a.replace(hour=9,minute=1),sample(a))==[]
    b=a.replace(hour=13,minute=45)
    second=main.predict(b,sample(b))
    assert len(second)==2
    assert next(x for x in second if x["market"]=="588940")["target_session"]=="2026-11-13"
    assert len(main.ledger("predictions.jsonl"))==4


def test_settle_only_after_official_close(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DATA",tmp_path)
    a=datetime(2026,11,12,8,45,tzinfo=CN)
    main.predict(a,sample(a))
    assert main.settle(a.replace(hour=14),sample(a))==[]
    close=a.replace(hour=16,minute=15)
    settled=main.settle(close,sample(close))
    etf=[x for x in settled if x["market"]=="588940"]
    assert len(etf)==1 and etf[0]["correct"]
    assert main.settle(close,sample(close))==[]


def test_quote_validation_and_no_unverified_premium():
    assert main.parse_quote_time("20261112142530")
    assert main.parse_quote_time(None) is None
    assert main.num(None) is None
    s=sample(datetime(2026,11,12,13,45,tzinfo=CN))
    assert s["quotes"]["513650"]["premium_pct"] is None


def test_run_writes_page(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"ROOT",tmp_path)
    monkeypatch.setattr(main,"DATA",tmp_path/"data")
    monkeypatch.setattr(main,"DOCS",tmp_path/"docs")
    a=datetime(2026,11,12,8,45,tzinfo=CN)
    s=main.run(a,reader=sample)
    assert s["slot"]=="09"
    assert (tmp_path/"docs"/"latest.json").is_file()
    assert "588940" in (tmp_path/"docs"/"index.html").read_text()
    assert (tmp_path/"data"/"predictions.jsonl").exists()
