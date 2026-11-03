"""Dashboards as code: build a Superset import bundle (a zip of YAML; JSON is valid YAML) from the definitions below.

Stable uuids mean re-importing updates the same database, datasets, charts and dashboards. The bundle connects as
analytics_ro, which can only read the analytics tables and views.
"""

import json
import os
import sys
import time
import uuid
import zipfile
from urllib.parse import quote

NAMESPACE = uuid.UUID("7f0e4d1a-3a55-4a39-9c44-5c3f9d6a1b20")
DATABASE_NAME = "Streaming analytics"


def uid(kind, name):
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{name}"))


TIME_FILTER = [
    {
        "clause": "WHERE",
        "subject": "date",
        "operator": "TEMPORAL_RANGE",
        "comparator": "No filter",
        "expressionType": "SIMPLE",
    }
]

# ---------- Datasets ----------


def metric(name, expression, label, fmt=None):
    return {"metric_name": name, "expression": expression, "verbose_name": label, "d3format": fmt}


WATCH_HOURS = "SUM(watch_time_sec) / 3600.0"
DATASETS = {
    "daily_platform_stats": {
        "columns": {
            "date": "DATE",
            "views": "INTEGER",
            "sessions": "INTEGER",
            "unique_viewers": "INTEGER",
            "watch_time_sec": "FLOAT",
            "videos_watched": "INTEGER",
            "new_uploads": "INTEGER",
        },
        "metrics": [
            metric("views", "SUM(views)", "Views", ",d"),
            metric("watch_hours", WATCH_HOURS, "Watch hours", ",.1f"),
            # Daily unique viewers can't be summed over days: one person is counted once per day.
            metric("avg_daily_viewers", "AVG(unique_viewers)", "Avg daily viewers", ",.0f"),
            metric("daily_viewers", "MAX(unique_viewers)", "Viewers", ",d"),
            metric("uploads", "SUM(new_uploads)", "New uploads", ",d"),
        ],
    },
    "analytics_video_stats": {
        "columns": {
            "date": "DATE",
            "video_id": "UUID",
            "title": "VARCHAR",
            "views": "INTEGER",
            "unique_viewers": "INTEGER",
            "watch_time_sec": "FLOAT",
            "avg_completion_pct": "FLOAT",
            "completions": "INTEGER",
            "buffering_events": "INTEGER",
            "buffering_ms": "BIGINT",
        },
        "metrics": [
            metric("views", "SUM(views)", "Views", ",d"),
            metric("watch_hours", WATCH_HOURS, "Watch hours", ",.1f"),
            # Weighted by views: a day with 1 view must not count as much as a day with 1000.
            metric("avg_completion", "SUM(avg_completion_pct * views) / NULLIF(SUM(views), 0)", "Avg % watched", ".1f"),
            metric("completion_rate", "100.0 * SUM(completions) / NULLIF(SUM(views), 0)", "Finished %", ".1f"),
            metric("stalls", "SUM(buffering_events)", "Stalls", ",d"),
        ],
    },
    "analytics_video_retention": {
        "columns": {
            "date": "DATE",
            "video_id": "UUID",
            "title": "VARCHAR",
            "position_pct": "INTEGER",
            "viewers": "INTEGER",
        },
        "metrics": [metric("viewers", "SUM(viewers)", "Viewers", ",d")],
    },
    "daily_streaming_quality": {
        "columns": {
            "date": "DATE",
            "device": "VARCHAR",
            "country": "VARCHAR",
            "quality": "VARCHAR",
            "sessions": "INTEGER",
            "watch_time_sec": "FLOAT",
            "buffering_events": "INTEGER",
            "buffering_ms": "BIGINT",
            "startup_events": "INTEGER",
            "startup_ms": "BIGINT",
            "quality_changes": "INTEGER",
        },
        "metrics": [
            metric("watch_hours", WATCH_HOURS, "Watch hours", ",.1f"),
            metric(
                "rebuffer_ratio",
                "100.0 * SUM(buffering_ms) / 1000.0 / NULLIF(SUM(watch_time_sec), 0)",
                "Rebuffer ratio %",
                ".2f",
            ),
            metric(
                "stalls_per_hour",
                "SUM(buffering_events) / NULLIF(SUM(watch_time_sec) / 3600.0, 0)",
                "Stalls per hour",
                ".1f",
            ),
            metric(
                "avg_startup_ms", "1.0 * SUM(startup_ms) / NULLIF(SUM(startup_events), 0)", "Avg startup (ms)", ",.0f"
            ),
            metric("quality_switches", "SUM(quality_changes)", "Quality switches", ",d"),
        ],
    },
}

# ---------- Charts ----------


def big_number(dataset, name, metric_name, subheader):
    return {
        "name": name,
        "dataset": dataset,
        "viz_type": "big_number_total",
        "params": {"metric": metric_name, "subheader": subheader, "header_font_size": 0.4, "subheader_font_size": 0.15},
    }


def series(viz_type, dataset, name, x_axis, metrics, groupby=(), **extra):
    params = {
        "x_axis": x_axis,
        "metrics": list(metrics),
        "groupby": list(groupby),
        "show_legend": True,
        "rich_tooltip": True,
        "row_limit": 10000,
        "x_axis_title_margin": 30,
        "y_axis_title_margin": 30,
        **extra,
    }
    if x_axis == "date":
        params["time_grain_sqla"] = "P1D"
    return {"name": name, "dataset": dataset, "viz_type": viz_type, "params": params}


def table(dataset, name, groupby, metrics, order_by, row_limit=50):
    return {
        "name": name,
        "dataset": dataset,
        "viz_type": "table",
        "params": {
            "query_mode": "aggregate",
            "groupby": groupby,
            "metrics": metrics,
            "order_desc": True,
            "timeseries_limit_metric": order_by,
            "row_limit": row_limit,
            "table_timestamp_format": "smart_date",
        },
    }


def pie(dataset, name, groupby, metric_name):
    return {
        "name": name,
        "dataset": dataset,
        "viz_type": "pie",
        "params": {
            "groupby": [groupby],
            "metric": metric_name,
            "row_limit": 20,
            "show_labels": True,
            "label_type": "percent",
            "donut": True,
            "show_legend": True,
        },
    }


LINE, BAR, AREA = "echarts_timeseries_line", "echarts_timeseries_bar", "echarts_area"
P, V, R, Q = "daily_platform_stats", "analytics_video_stats", "analytics_video_retention", "daily_streaming_quality"

DASHBOARDS = {
    "platform-overview": {
        "title": "Platform overview",
        "filters": [],
        "rows": [
            [
                big_number(P, "Views", "views", "in the selected period"),
                big_number(P, "Watch hours", "watch_hours", "in the selected period"),
                big_number(P, "Avg daily viewers", "avg_daily_viewers", "unique viewers per day"),
                big_number(P, "New uploads", "uploads", "in the selected period"),
            ],
            [
                series(LINE, P, "Views per day", "date", ["views"]),
                series(LINE, P, "Unique viewers per day", "date", ["daily_viewers"]),
            ],
            [
                series(BAR, P, "Watch hours per day", "date", ["watch_hours"]),
                table(V, "Top videos", ["title"], ["views", "watch_hours", "avg_completion"], "views", 10),
            ],
        ],
    },
    "video-retention": {
        "title": "Video retention",
        "filters": [("Video", V, "title")],
        "rows": [
            [
                series(
                    LINE,
                    R,
                    "Audience retention: viewers at each point of the video",
                    "position_pct",
                    ["viewers"],
                    ["title"],
                    x_axis_title="Position in video (%)",
                    y_axis_title="Viewers",
                    x_axis_sort="position_pct",
                    x_axis_sort_asc=True,
                    show_markers=True,
                )
            ],
            [
                table(
                    V,
                    "Videos",
                    ["title"],
                    ["views", "watch_hours", "avg_completion", "completion_rate", "stalls"],
                    "views",
                ),
                series(LINE, V, "Views per day by video", "date", ["views"], ["title"]),
            ],
        ],
    },
    "streaming-quality": {
        "title": "Streaming quality",
        # DB-IP's license asks for this link wherever its results are shown.
        "note": "Countries: [IP Geolocation by DB-IP](https://db-ip.com)",
        "filters": [("Device", Q, "device"), ("Country", Q, "country")],
        "rows": [
            [
                big_number(Q, "Rebuffer ratio", "rebuffer_ratio", "% of watch time spent stalled"),
                big_number(Q, "Stalls per hour", "stalls_per_hour", "of playback"),
                big_number(Q, "Avg startup time", "avg_startup_ms", "milliseconds"),
                big_number(Q, "Quality switches", "quality_switches", "in the selected period"),
            ],
            [
                series(BAR, Q, "Rebuffer ratio by device", "device", ["rebuffer_ratio"], show_legend=False),
                series(BAR, Q, "Rebuffer ratio by country", "country", ["rebuffer_ratio"], show_legend=False),
            ],
            [
                pie(Q, "Watch time by rendition", "quality", "watch_hours"),
                series(AREA, Q, "Watch hours by rendition", "date", ["watch_hours"], ["quality"], stack="Stack"),
            ],
            [series(LINE, Q, "Avg startup time per day", "date", ["avg_startup_ms"])],
        ],
    },
}

# ---------- Superset's export format ----------


def database_yaml():
    password = quote(os.environ["ANALYTICS_RO_PASSWORD"], safe="")
    host = os.environ.get("ANALYTICS_DB_HOST", "postgres")
    name = os.environ.get("ANALYTICS_DB_NAME", "streaming")
    return {
        "database_name": DATABASE_NAME,
        "sqlalchemy_uri": f"postgresql+psycopg2://analytics_ro:{password}@{host}:5432/{name}",
        "uuid": uid("database", DATABASE_NAME),
        "version": "1.0.0",
        "expose_in_sqllab": True,
        "allow_ctas": False,
        "allow_cvas": False,
        "allow_dml": False,
        "allow_csv_upload": False,
        "allow_run_async": False,
        "extra": {},
    }


COLUMN_LABELS = {"title": "Video", "device": "Device", "country": "Country", "quality": "Rendition"}


def dataset_yaml(name, spec):
    return {
        "table_name": name,
        "main_dttm_col": "date",
        "schema": "public",
        "uuid": uid("dataset", name),
        "database_uuid": uid("database", DATABASE_NAME),
        "version": "1.0.0",
        "columns": [
            {
                "column_name": column,
                "verbose_name": COLUMN_LABELS.get(column),
                "type": kind,
                "is_dttm": kind == "DATE",
                "filterable": True,
                "groupby": True,
            }
            for column, kind in spec["columns"].items()
        ],
        "metrics": spec["metrics"],
    }


def chart_key(dashboard, chart):
    return f"{dashboard}:{chart['name']}"


def chart_yaml(dashboard, chart):
    dataset = chart["dataset"]
    params = {
        "viz_type": chart["viz_type"],
        "datasource": f"{uid('dataset', dataset)}__table",
        "adhoc_filters": TIME_FILTER,
        **chart["params"],
    }
    return {
        "slice_name": chart["name"],
        "viz_type": chart["viz_type"],
        "params": params,
        "cache_timeout": None,
        "uuid": uid("chart", chart_key(dashboard, chart)),
        "dataset_uuid": uid("dataset", dataset),
        "version": "1.0.0",
    }


GRID_COLUMNS = 12


def position_tree(dashboard, spec):
    tree = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": spec["title"]}},
    }
    for r, charts in enumerate(spec["rows"]):
        row_id = f"ROW-{r}"
        tree["GRID_ID"]["children"].append(row_id)
        width = GRID_COLUMNS // len(charts)
        is_numbers = all(c["viz_type"] == "big_number_total" for c in charts)
        tree[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for c, chart in enumerate(charts):
            chart_id = f"CHART-{r}-{c}"
            tree[row_id]["children"].append(chart_id)
            tree[chart_id] = {
                "type": "CHART",
                "id": chart_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                # chartId is a placeholder: the importer swaps it for the real id via uuid.
                "meta": {
                    "chartId": r * 100 + c + 1,
                    "width": width,
                    "height": 26 if is_numbers else 60,
                    "uuid": uid("chart", chart_key(dashboard, chart)),
                    "sliceName": chart["name"],
                },
            }
    if "note" in spec:
        tree["GRID_ID"]["children"].append("ROW-note")
        tree["ROW-note"] = {
            "type": "ROW",
            "id": "ROW-note",
            "children": ["MARKDOWN-note"],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        tree["MARKDOWN-note"] = {
            "type": "MARKDOWN",
            "id": "MARKDOWN-note",
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID", "ROW-note"],
            "meta": {"code": spec["note"], "width": GRID_COLUMNS, "height": 8},
        }
    return tree


def native_filters(dashboard, spec):
    filters = [
        {
            "id": "NATIVE_FILTER-time",
            "name": "Period",
            "filterType": "filter_time",
            "targets": [{}],
            "controlValues": {},
            "defaultDataMask": {
                "extraFormData": {"time_range": "Last 30 days"},
                "filterState": {"value": "Last 30 days"},
            },
            "cascadeParentIds": [],
            "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            "type": "NATIVE_FILTER",
            "description": "",
        }
    ]
    for name, dataset, column in spec["filters"]:
        filters.append(
            {
                "id": f"NATIVE_FILTER-{column}",
                "name": name,
                "filterType": "filter_select",
                "targets": [{"column": {"name": column}, "datasetUuid": uid("dataset", dataset)}],
                "controlValues": {"multiSelect": True, "enableEmptyFilter": False, "searchAllOptions": False},
                "defaultDataMask": {"extraFormData": {}, "filterState": {}},
                "cascadeParentIds": [],
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                "type": "NATIVE_FILTER",
                "description": "",
            }
        )
    return filters


def dashboard_yaml(slug, spec):
    return {
        "dashboard_title": spec["title"],
        "slug": slug,
        "uuid": uid("dashboard", slug),
        "position": position_tree(slug, spec),
        "metadata": {
            "native_filter_configuration": native_filters(slug, spec),
            "color_scheme": "supersetColors",
            "refresh_frequency": 0,
            "timed_refresh_immune_slices": [],
        },
        "published": True,
        "version": "1.0.0",
    }


def bundle_files():
    files = {
        "metadata.yaml": {
            "version": "1.0.0",
            "type": "Dashboard",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        },
        "databases/streaming_analytics.yaml": database_yaml(),
    }
    for name, spec in DATASETS.items():
        files[f"datasets/streaming_analytics/{name}.yaml"] = dataset_yaml(name, spec)
    for slug, spec in DASHBOARDS.items():
        files[f"dashboards/{slug}.yaml"] = dashboard_yaml(slug, spec)
        for row in spec["rows"]:
            for chart in row:
                key = uid("chart", chart_key(slug, chart))[:8]
                files[f"charts/{slug}-{key}.yaml"] = chart_yaml(slug, chart)
    return files


def main(path):
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in bundle_files().items():
            bundle.writestr(f"streaming_dashboards/{name}", json.dumps(content, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main(sys.argv[1])
