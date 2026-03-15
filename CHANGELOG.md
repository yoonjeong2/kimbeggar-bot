# Changelog

All notable changes to KimBeggar are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- `data_agent/position_store.py` — SQLite-backed `PositionStore` class; entry prices
  now survive bot restarts (`data/bot_state.db`).
- `strategy.signal.is_market_open()` — Korean market hours filter (weekdays 09:00–15:30);
  `run_cycle()` skips execution outside trading hours.
- `tests/test_position_store.py` — CRUD + upsert coverage for `PositionStore`.
- `tests/test_main.py` — market-hours skip test; `PositionStore` mock injection.
- `tests/test_strategy.py` — `TestIsMarketOpen` class covering all boundary cases.

### Changed
- `main.py` — `entry_prices` dict replaced with `PositionStore` instance;
  `run_cycle()` parameter renamed from `entry_prices` to `position_store`.
- `main.py` — `run_cycle()` docstring updated to reflect persistent position storage.

---

## [0.6.0] — 2024-xx-xx (877ca1c)

### Added
- `Dockerfile` and Docker Compose for containerised deployment.
- GitHub Actions Docker CI workflow (`docker-ci.yml`).
- README sections: contributor guide and 2022 back-test scenario walk-through.

### Changed
- Test coverage raised to **92 %** (branch + line).

---

## [0.5.0] — 2024-xx-xx (2ec64d5)

### Added
- Full pytest test suite (`tests/test_strategy.py`, `tests/test_main.py`,
  `tests/test_notifier.py`, `tests/test_data_agent.py`).
- `conftest.py` with shared fixtures (`mock_settings`, `ascending_prices`,
  `ohlcv_ascending`, etc.).
- `black` and `pylint` automation via `Makefile` and CI.
- MVP demo script (`demo.py`) with synthetic walk-through.

### Changed
- README upgraded with architecture diagram and quick-start guide.

---

## [0.4.0] — 2024-xx-xx (0c64e81)

### Added
- `backtest/` module using `backtrader` for historical strategy simulation.
- TA-Lib optional dependency note in `requirements.txt`.

---

## [0.3.0] — 2024-xx-xx (78fa626)

### Changed
- Replaced `ta` library with pure **pandas / numpy** indicator implementations
  (`strategy/indicators.py`) — eliminates C-extension build dependency.

### Fixed
- KIS API error handling hardened: HTTP 4xx/5xx responses now raise descriptive
  exceptions instead of silently returning empty data.

---

## [0.2.1] — 2024-xx-xx (47729b2)

### Added
- `.claude/requirements.md` — module implementation status, AI usage log,
  and change log for internal tracking.

---

## [0.2.0] — 2024-xx-xx (6c90711)

### Added
- Core trading logic: `strategy/signal.py` (`SignalEngine`, `Signal`, `SignalType`).
- `strategy/indicators.py` — RSI, SMA, EMA, golden/dead cross, volatility.
- `strategy/hedge_logic.py` — dynamic hedge-ratio calculation.
- `notifier/kakao.py` — KakaoTalk notification integration.
- `main.py` — scheduling loop with `schedule` library.
- GitHub Actions CI pipeline (lint + test).

---

## [0.1.0] — 2024-xx-xx (80b4d5c)

### Added
- Initial commit: project architecture and KIS (Korea Investment & Securities) API
  integration (`data_agent/kis_api.py`).
- `config/settings.py` — environment-variable based configuration via `pydantic`.
- `logger/log_setup.py` — structured logging setup.
