#!/usr/bin/env python3
"""Which infrastructure this workspace defines — so the HLD asks infrastructure questions only
when the codebase makes them relevant.

  infra_scan.py [--root .] [--out <profile.json>]

Scans every discovered repository (codebase_scan.discover_repos) for infrastructure definitions:
  infrastructure as code   Terraform (*.tf), Helm (Chart.yaml), Kubernetes manifests or Kustomize,
                           Pulumi, AWS CDK, CloudFormation, Serverless, Ansible
  containers               Dockerfile, Docker Compose

and reports a level:
  iac         some repository holds infrastructure as code: ask every material infrastructure
              decision the feature changes (scaling, data stores, messaging, networking, secrets,
              rollout, observability, cost)
  containers  only container definitions: ask only runtime/config questions the feature changes
  none        no infrastructure definitions: ask no infrastructure questions

maestro.config.yaml may override: `infrastructure: {level: none|containers|iac}` (for example when
another team owns the infrastructure), and a repository's `role: infra` marks it an infrastructure
repository whatever its files say.

Prints one JSON line {level, platforms_csv, iac_repos_csv, container_repos_csv, repos_csv,
summary, profile_path} and writes the per-repository evidence to --out. Always exits 0.
"""
import argparse
import fnmatch
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import project_config  # noqa: E402

LEVELS = ("none", "containers", "iac")
IAC = ("terraform", "helm", "kubernetes", "pulumi", "cdk", "cloudformation", "serverless", "ansible")
CONTAINERS = ("docker", "docker-compose")
FILE_SIGNALS = (  # (platform, filename glob)
    ("terraform", "*.tf"),
    ("helm", "Chart.yaml"),
    ("kubernetes", "kustomization.yaml"),
    ("kubernetes", "kustomization.yml"),
    ("pulumi", "Pulumi.yaml"),
    ("pulumi", "Pulumi.yml"),
    ("cdk", "cdk.json"),
    ("serverless", "serverless.yml"),
    ("serverless", "serverless.yaml"),
    ("ansible", "ansible.cfg"),
    ("docker", "Dockerfile"),
    ("docker", "Dockerfile.*"),
    ("docker", "*.Dockerfile"),
    ("docker-compose", "docker-compose*.yml"),
    ("docker-compose", "docker-compose*.yaml"),
    ("docker-compose", "compose.yml"),
    ("docker-compose", "compose.yaml"),
)
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target", ".terraform", "venv",
             ".venv", "__pycache__", ".next", ".gradle", ".idea", ".maestro"}
K8S_KIND_RE = re.compile(r"^kind:\s*(Deployment|StatefulSet|DaemonSet|Service|Ingress|CronJob|Job|"
                         r"HorizontalPodAutoscaler|ConfigMap|Secret|Namespace)\s*$", re.M)
MAX_FILES = 20000
MAX_EVIDENCE = 5
SNIFF_BYTES = 4096


def _sniff(path):
    try:
        if os.path.getsize(path) > 512 * 1024:
            return ""
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(SNIFF_BYTES)
    except OSError:
        return ""


WORKSPACE = "(workspace root)"


def scan_repo(path, skip=()):
    """{platform: [evidence paths relative to the repo]} for one repository."""
    found, seen = {}, 0
    skip = {os.path.realpath(p) for p in skip}
    for dirpath, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and os.path.realpath(os.path.join(dirpath, d)) not in skip)
        for name in sorted(files):
            seen += 1
            if seen > MAX_FILES:
                return found
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, path)
            platforms = {platform for platform, glob in FILE_SIGNALS if fnmatch.fnmatch(name, glob)}
            if name.endswith((".yaml", ".yml", ".json", ".template")) and not platforms:
                head = _sniff(full)
                if "AWSTemplateFormatVersion" in head:
                    platforms.add("cloudformation")
                elif re.search(r"^apiVersion:", head, re.M) and K8S_KIND_RE.search(head):
                    platforms.add("kubernetes")
            for platform in platforms:
                evidence = found.setdefault(platform, [])
                if len(evidence) < MAX_EVIDENCE:
                    evidence.append(rel)
    return found


def profile(root):
    config = {}
    try:
        config = project_config.load(root) or {}
    except project_config.ConfigError:
        pass
    repos_config = config.get("repos") if isinstance(config.get("repos"), dict) else {}
    discovered = codebase_scan.discover_repos(root)
    targets = list(discovered)
    if os.path.realpath(root) not in {os.path.realpath(p) for _n, p in discovered}:
        # an umbrella workspace: infrastructure at its root (compose files, an infra/ folder)
        # counts too; the repositories under it are scanned on their own
        targets.append((WORKSPACE, root))
    repos = []
    for name, path in targets:
        platforms = scan_repo(path, skip=[p for _n, p in discovered] if name == WORKSPACE else ())
        role = ((repos_config.get(name) or {}) if isinstance(repos_config.get(name), dict)
                else {}).get("role")
        iac = sorted(p for p in platforms if p in IAC)
        repos.append({
            "repo": name,
            "role": role or ("infra" if iac else "app"),
            "platforms": sorted(platforms),
            "evidence": platforms,
        })
    iac_repos = [r["repo"] for r in repos
                 if r["role"] == "infra" or any(p in IAC for p in r["platforms"])]
    container_repos = [r["repo"] for r in repos if any(p in CONTAINERS for p in r["platforms"])]
    detected = "iac" if iac_repos else "containers" if container_repos else "none"
    override = (config.get("infrastructure") or {}).get("level") \
        if isinstance(config.get("infrastructure"), dict) else None
    level = override if override in LEVELS else detected
    platforms = sorted({p for r in repos for p in r["platforms"]})
    return {
        "schema_version": 1,
        "level": level,
        "detected_level": detected,
        "overridden": level != detected,
        "platforms": platforms,
        "iac_repos": iac_repos,
        "container_repos": container_repos,
        "repos": repos,
    }


def summarize(doc):
    by_repo = {r["repo"]: r for r in doc["repos"]}

    def describe(names, kinds):
        return ", ".join(
            f"{name} ({', '.join(p for p in by_repo[name]['platforms'] if p in kinds) or 'role: infra'})"
            for name in names)
    parts = []
    if doc["iac_repos"]:
        parts.append("infrastructure as code in " + describe(doc["iac_repos"], IAC))
    if doc["container_repos"]:
        parts.append("containers in " + describe(doc["container_repos"], CONTAINERS))
    found = "; ".join(parts) or "no infrastructure definitions in this workspace"
    rule = {
        "iac": "ask every material infrastructure decision this feature changes or depends on",
        "containers": "ask only the runtime and configuration questions this feature changes",
        "none": "ask no infrastructure questions",
    }[doc["level"]]
    override = " (set in maestro.config.yaml)" if doc["overridden"] else ""
    return f"Infrastructure level {doc['level']}{override}: {found[0].upper() + found[1:]} — {rule}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    doc = profile(args.root)
    doc["summary"] = summarize(doc)
    path = ""
    if args.out:
        full = args.out if os.path.isabs(args.out) else os.path.join(args.root, args.out)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        path = os.path.relpath(full, args.root)
    print(json.dumps({
        "level": doc["level"],
        "platforms_csv": ",".join(doc["platforms"]),
        "iac_repos_csv": ",".join(doc["iac_repos"]),
        "container_repos_csv": ",".join(doc["container_repos"]),
        "repos_csv": ",".join(r["repo"] for r in doc["repos"] if r["repo"] != WORKSPACE),
        "summary": doc["summary"],
        "profile_path": path,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
