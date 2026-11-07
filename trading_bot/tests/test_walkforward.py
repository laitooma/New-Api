import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import strategies as st
import walkforward as wfm

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_test_windows_never_overlap_and_follow_training():
    grid = {f"sma{n}": (lambda df, n=n: st.sma_trend(df, n)) for n in (30, 60)}
    wf = wfm.walk_forward(grid, st.sma_ensemble)
    starts = pd.to_datetime(wf["test_start"])
    assert len(wf) >= 5
    assert (starts.diff().dropna() >= pd.Timedelta(days=wfm.TEST_DAYS)).all()


def test_baseline_against_itself_is_never_promoted():
    wf = wfm.walk_forward({"same": st.sma_ensemble}, st.sma_ensemble)
    assert (wf["candidate_%"] == wf["baseline_%"]).all()
    assert wfm.verdict(wf)["promote"] is False


def test_winning_often_but_losing_in_total_is_rejected():
    wf = pd.DataFrame({"candidate_%": [1, 1, 1, 1, -10], "baseline_%": [0, 0, 0, 0, 0]})
    v = wfm.verdict(wf)
    assert v["windows_won_%"] == 80 and v["promote"] is False


def test_clear_winner_is_promoted():
    wf = pd.DataFrame({"candidate_%": [2, 2, 2, -1, 2], "baseline_%": [0, 0, 0, 0, 0]})
    assert wfm.verdict(wf)["promote"] is True


def test_best_single_sma_is_not_robust_enough():
    """Documented on 2026-11-07: promoted in only 4 of 16 window settings."""
    grid = {
        f"sma{n}": (lambda df, n=n: st.sma_trend(df, n)) for n in range(20, 160, 10)
    }
    assert wfm.robust_verdict(grid, st.sma_ensemble)["promote"] is False
