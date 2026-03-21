# BetWise Audit Fix Deployment Checklist

## Changes Summary (9 files, 128 insertions, 64 deletions)

| Fix | File | Change |
|-----|------|--------|
| MODEL_DIR + permissions | Dockerfile | ENV MODEL_DIR, chown appuser |
| Celery memory limit | start.sh | --max-memory-per-child=1024000 |
| Retrain retry logic | prediction_tasks.py | bind=True, SoftTimeLimitExceeded, self.retry |
| Early stopping | retrain.py, train.py | early_stopping_rounds=50 in constructor (XGBoost 3.x) |
| NaN for missing data | ml_model.py | _weighted_avg returns NaN not 0.0 |
| Error logging | retrain.py | Always log errors, abort if >10% fail |
| Batch DB sessions | retrain.py | 500-fixture batches |
| MIN_EDGE threshold | config.py, .env | 0.02 -> 0.05 |
| ODDS_MAX threshold | config.py, .env | 2.50 -> 5.00 |
| Confidence score | prediction_engine.py | Replace edge component with prob decisiveness |
| Remove H2H placeholder | prediction_engine.py | Redistribute to market consensus (20pts) |
| Value bet dedup | prediction_engine.py | One value bet per market (highest edge) |
| Remove num_class passing | retrain.py, train.py | XGBoost 3.x auto-infers from labels |
| Quality gate | retrain.py | Reject accuracy < 0.30, warn if >10% worse |
| Memory logging | retrain.py, requirements.txt | psutil process memory tracking |

## Pre-Deploy

- [x] Dockerfile has `ENV MODEL_DIR=/app/ml/models`
- [x] Dockerfile has `RUN chown -R appuser:appuser /app/ml/models` before USER line
- [x] start.sh has `--max-memory-per-child=1024000`
- [x] psutil in backend/requirements.txt
- [x] All 4 `.fit()` calls have `early_stopping_rounds` in constructor params (XGBoost 3.x compatible)
- [x] No `params["num_class"]` passed to XGBClassifier (but still in MARKETS dict for evaluate_model)
- [x] 19/19 smoke tests pass
- [ ] Railway env vars updated: `MIN_EDGE=0.05`, `ODDS_MAX=5.00`

## Deploy

- [ ] Push to main
- [ ] Watch Railway build logs -- verify Docker build succeeds
- [ ] Check Railway runtime logs -- verify app starts, models load from /app/ml/models/

## Immediate Post-Deploy (do within 1 hour)

- [ ] Hit `GET /api/admin/retrain-logs?limit=5` -- record the error_message from recent failures
  - If it says PermissionError or FileNotFoundError -> our fix was correct
  - If it says something else -> investigate further
- [ ] Update Railway env vars: `MIN_EDGE=0.05`, `ODDS_MAX=5.00`
- [ ] Trigger manual retrain from admin dashboard (`POST /api/admin/retrain`)
- [ ] Watch Railway logs for:
  - "Retrain starting" message with memory info
  - Per-market training progress
  - "Saved model" messages (proves MODEL_DIR + permissions are fixed)
  - Final "Retrain complete: 4/4 markets succeeded"
- [ ] Check retrain-logs endpoint again -- verify new entry has status="success"
- [ ] Wait for next scheduled prediction run (or trigger manually) -- verify predictions include ML probabilities

## 1-Week Monitoring

- [ ] Day 1-2: Value bet count should be LOWER (higher MIN_EDGE filters more)
- [ ] Day 3: Check if scheduled Monday retrain (celery_beat) succeeds too
- [ ] Day 7: Compare P&L trend vs previous 7 days
- [ ] If P&L is still negative after 2 weeks, next step is probability calibration (isotonic regression)
