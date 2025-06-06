# mypy: allow-untyped-defs

import json
import re

from mozlog.structured.formatters.base import BaseFormatter
from ..executors.base import strip_server


LONE_SURROGATE_RE = re.compile("[\uD800-\uDFFF]")


def surrogate_replacement(match):
    return "U+" + hex(ord(match.group()))[2:]


def replace_lone_surrogate(data):
    return LONE_SURROGATE_RE.subn(surrogate_replacement, data)[0]


class WptreportFormatter(BaseFormatter):  # type: ignore
    """Formatter that produces results in the format that wptreport expects."""

    def __init__(self):
        self.raw_results = {}
        self.results = {}

    def suite_start(self, data):
        self.results["run_info"] = data.get("run_info", {})
        self.results["time_start"] = data["time"]
        self.results["results"] = []
        self.results["subsuites"] = {}

    def add_subsuite(self, data):
        self.results["subsuites"][data["name"]] = data.get("run_info", {})

    def suite_end(self, data):
        self.results["time_end"] = data["time"]
        for subsuite, results in self.raw_results.items():
            for test_name, result in results.items():
                result["test"] = test_name
                result["subsuite"] = subsuite
                self.results["results"].append(result)
        return json.dumps(self.results) + "\n"

    def find_or_create_test(self, data):
        subsuite = data.get("subsuite", "")
        test_name = data["test"]
        subsuite_results = self.raw_results.setdefault(subsuite, {})
        return subsuite_results.setdefault(test_name, {"subtests": [],
                                                      "status": "",
                                                      "message": None})

    def test_start(self, data):
        test = self.find_or_create_test(data)
        test["start_time"] = data["time"]

    def create_subtest(self, data):
        test = self.find_or_create_test(data)
        subtest_name = replace_lone_surrogate(data["subtest"])

        subtest = {
            "name": subtest_name,
            "status": "",
            "message": None
        }
        test["subtests"].append(subtest)

        return subtest

    def test_status(self, data):
        subtest = self.create_subtest(data)
        subtest["status"] = data["status"]
        if "expected" in data:
            subtest["expected"] = data["expected"]
        if "known_intermittent" in data:
            subtest["known_intermittent"] = data["known_intermittent"]
        if "message" in data:
            subtest["message"] = replace_lone_surrogate(data["message"])

    def test_end(self, data):
        test = self.find_or_create_test(data)
        start_time = test.pop("start_time")
        test["duration"] = data["time"] - start_time
        test["status"] = data["status"]
        if "expected" in data:
            test["expected"] = data["expected"]
        if "known_intermittent" in data:
            test["known_intermittent"] = data["known_intermittent"]
        if "message" in data:
            test["message"] = replace_lone_surrogate(data["message"])
        if "reftest_screenshots" in data.get("extra", {}):
            test["screenshots"] = {
                strip_server(item["url"]): "sha1:" + item["hash"]
                for item in data["extra"]["reftest_screenshots"]
                if isinstance(item, dict)
            }
        test_name = data["test"]
        subsuite = data.get("subsuite", "")
        result = {"test": test_name,
                  "subsuite": subsuite}
        result.update(self.raw_results[subsuite][test_name])
        self.results["results"].append(result)
        self.raw_results[subsuite].pop(test_name)

    def assertion_count(self, data):
        test = self.find_or_create_test(data)
        test["asserts"] = {
            "count": data["count"],
            "min": data["min_expected"],
            "max": data["max_expected"]
        }

    def lsan_leak(self, data):
        if "lsan_leaks" not in self.results:
            self.results["lsan_leaks"] = []
        lsan_leaks = self.results["lsan_leaks"]
        lsan_leaks.append({"frames": data["frames"],
                           "scope": data["scope"],
                           "allowed_match": data.get("allowed_match"),
                           "subsuite": data.get("subsuite", "")})

    def find_or_create_mozleak(self, data):
        if "mozleak" not in self.results:
            self.results["mozleak"] = {}
        scope = data["scope"]
        if scope not in self.results["mozleak"]:
            self.results["mozleak"][scope] = {"objects": [], "total": []}
        return self.results["mozleak"][scope]

    def mozleak_object(self, data):
        scope_data = self.find_or_create_mozleak(data)
        scope_data["objects"].append({"process": data["process"],
                                      "name": data["name"],
                                      "allowed": data.get("allowed", False),
                                      "bytes": data["bytes"],
                                      "subsuite": data.get("subsuite", "")})

    def mozleak_total(self, data):
        scope_data = self.find_or_create_mozleak(data)
        scope_data["total"].append({"bytes": data["bytes"],
                                    "threshold": data.get("threshold", 0),
                                    "process": data["process"],
                                    "subsuite": data.get("subsuite", "")})
