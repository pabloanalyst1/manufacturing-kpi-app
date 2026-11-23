"""Manufacturing KPI pipeline: OEE, downtime, changeovers and scrap for a PET packaging plant.

Steps:
  1/6 EXTRACT    - generate the synthetic MES shift documents and ERP extracts (messy, like the real thing)
  2/6 LAND       - save the raw files; load the MES documents into MongoDB
  3/6 FLATTEN    - MongoDB aggregation pipelines -> raw_* tables in the SQLite warehouse
  4/6 TRANSFORM  - SQL models: staging -> dimensions -> facts -> marts
  5/6 QUALITY    - data quality checks (the pipeline stops if any fails)
  6/6 EXPORT     - marts to CSV for the BI tool

MongoDB is read from MONGO_URI (default mongodb://localhost:27017). If it is not reachable the documents are
flattened in Python from the local file instead, unless --require-mongo is given (used in CI).

Usage:
  python run_pipeline.py                      # default: Jan 2025 - Oct 2026, seed 42
  python run_pipeline.py --seed 7 --require-mongo
"""
from __future__ import annotations

import argparse
import logging
import time

from src.config import PipelineConfig
from src.export import export_marts
from src.generate_data import generate_all
from src.load import load_raw, save_raw_files
from src.mongo_store import extract_raw_tables
from src.quality import run_quality_checks
from src.transform import run_sql_models

log = logging.getLogger("pipeline")


def run(cfg: PipelineConfig) -> str:
    t0 = time.perf_counter()
    log.info("1/6 EXTRACT   - simulating the plant %s to %s (seed %s)", cfg.start_date, cfg.end_date, cfg.seed)
    docs, erp = generate_all(seed=cfg.seed, start=cfg.start_date, end=cfg.end_date)
    log.info("              %s MES shift documents, %s resin lots", f"{len(docs):,}", len(erp["resin_lots"]))

    log.info("2/6 LAND      - raw files and MongoDB")
    save_raw_files(docs, erp, cfg.raw_dir)
    log.info("3/6 FLATTEN   - aggregation pipelines -> raw tables")
    mes, source = extract_raw_tables(docs, cfg.mongo_uri, cfg.mongo_db, cfg.require_mongo)
    load_raw(mes, erp, cfg.db_path, cfg.start_date, cfg.end_date)

    log.info("4/6 TRANSFORM - SQL models")
    run_sql_models(cfg.db_path, cfg.sql_dir)

    log.info("5/6 QUALITY   - data quality checks")
    run_quality_checks(cfg.db_path)

    log.info("6/6 EXPORT    - marts to CSV")
    export_marts(cfg.db_path, cfg.export_dir)

    log.info("Done in %.1f s (documents flattened in %s). Warehouse: %s",
             time.perf_counter() - t0, "MongoDB" if source == "mongodb" else "Python", cfg.db_path)
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42, help="random seed (same seed = same data)")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB connection string (default: $MONGO_URI or localhost)")
    parser.add_argument("--require-mongo", action="store_true", help="fail instead of falling back if MongoDB is unavailable")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    cfg = PipelineConfig(seed=args.seed, require_mongo=args.require_mongo)
    if args.mongo_uri:
        cfg.mongo_uri = args.mongo_uri
    run(cfg)


if __name__ == "__main__":
    main()
