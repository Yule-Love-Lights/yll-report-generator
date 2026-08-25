"""Thin wrapper over the Vikunja REST API (v2.5.x).

Only the handful of endpoints the report->task sync needs. Everything is
looked up by NAME at runtime (project title, view title, bucket titles,
usernames) so there are no numeric IDs to keep in sync with Railway
variables — rename-safe as long as the names in Vikunja match the config.

Auth: an API token created under Settings -> API Tokens in the Vikunja web
UI, sent as `Authorization: Bearer <token>`.
"""
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_BASE_URL = "https://tasks.yulelovelights.com"


class VikunjaError(RuntimeError):
    """Every failure this client raises, including transport failures.

    Callers catch this one type and keep going; a bare requests exception
    would escape their handlers and abort a whole sync run.
    """


class VikunjaClient:
    def __init__(self, base_url=None, token=None, timeout=30):
        base = (base_url or os.environ.get("VIKUNJA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api = f"{base}/api/v1"
        self.token = token or os.environ["VIKUNJA_API_TOKEN"]
        self.timeout = timeout
        self._label_cache = {}

        # Retry only failures where the request provably never reached the
        # server. Read timeouts and 5xx are deliberately NOT retried: this
        # client creates tasks with PUT/POST, and replaying a request that
        # may already have been applied would duplicate them.
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(
            total=4, connect=4, read=0, status=0, redirect=0,
            backoff_factor=1.0,
        ))
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # --- plumbing -------------------------------------------------------

    def _req(self, method, path, **kwargs):
        try:
            res = self._session.request(
                method,
                f"{self.api}{path}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as e:
            raise VikunjaError(f"{method} {path} -> transport failure: {e}") from e
        if res.status_code >= 400:
            raise VikunjaError(
                f"{method} {path} -> {res.status_code}: {res.text[:400]}"
            )
        if not res.content:
            return None
        return res.json()

    def _paginate(self, path, params=None):
        """Vikunja paginates with ?page=N; an empty array ends the walk."""
        params = dict(params or {})
        page = 1
        out = []
        while True:
            params["page"] = page
            batch = self._req("GET", path, params=params) or []
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 50:  # instance max_items_per_page
                break
            page += 1
        return out

    # --- discovery ------------------------------------------------------

    def get_project_by_title(self, title):
        for p in self._req("GET", "/projects", params={"s": title}) or []:
            if p.get("title", "").strip().lower() == title.strip().lower():
                return p
        raise VikunjaError(f"No project titled {title!r} found (check the API token's access).")

    def get_kanban_view(self, project_id):
        views = self._req("GET", f"/projects/{project_id}/views") or []
        for v in views:
            if v.get("view_kind") == "kanban":
                return v
        raise VikunjaError(f"Project {project_id} has no kanban view.")

    def get_buckets(self, project_id, view_id):
        """Returns {lowercased bucket title: bucket id}."""
        buckets = self._req("GET", f"/projects/{project_id}/views/{view_id}/buckets") or []
        return {b["title"].strip().lower(): b["id"] for b in buckets}

    def get_project_users(self, project_id):
        """Returns {lowercased username: user id} for everyone on the project."""
        users = self._req("GET", f"/projects/{project_id}/projectusers") or []
        return {u["username"].strip().lower(): u["id"] for u in users}

    # --- tasks ----------------------------------------------------------

    def list_open_tasks(self, project_id):
        """Every not-done task in one project.

        Deliberately NOT the project-view endpoint: on a kanban view that
        returns the view's *buckets*, not a flat task list. The global
        /tasks endpoint is the one that returns tasks — and the project_id
        clause is required, because without it this returns every task the
        token can see across all projects and the sync would dedupe today's
        action items against unrelated work.
        """
        return self._paginate(
            "/tasks",
            params={"filter": f"done = false && project_id = {int(project_id)}",
                    "per_page": 50},
        )

    def create_task(self, project_id, title, description="", due_date=None, priority=None):
        body = {"title": title, "description": description}
        if due_date:
            body["due_date"] = due_date
        if priority:
            body["priority"] = priority
        return self._req("PUT", f"/projects/{project_id}/tasks", json=body)

    def move_task_to_bucket(self, project_id, view_id, bucket_id, task_id):
        return self._req(
            "POST",
            f"/projects/{project_id}/views/{view_id}/buckets/{bucket_id}/tasks",
            json={"task_id": task_id, "bucket_id": bucket_id, "project_view_id": view_id},
        )

    def assign_user(self, task_id, user_id):
        return self._req("PUT", f"/tasks/{task_id}/assignees", json={"user_id": user_id})

    def add_comment(self, task_id, text):
        return self._req("PUT", f"/tasks/{task_id}/comments", json={"comment": text})

    # --- labels ---------------------------------------------------------

    def ensure_label(self, title, hex_color="4a7c59"):
        """Finds (or creates) a label by title and returns its id."""
        key = title.strip().lower()
        if key in self._label_cache:
            return self._label_cache[key]
        for l in self._req("GET", "/labels", params={"s": title}) or []:
            if l.get("title", "").strip().lower() == key:
                self._label_cache[key] = l["id"]
                return l["id"]
        created = self._req("PUT", "/labels", json={"title": title, "hex_color": hex_color})
        self._label_cache[key] = created["id"]
        return created["id"]

    def add_label(self, task_id, label_id):
        return self._req("PUT", f"/tasks/{task_id}/labels", json={"label_id": label_id})
