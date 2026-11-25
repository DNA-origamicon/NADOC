"""The retired cloud visualization must not remain in either public API."""
from backend.api.routes_md import router as md_router
from backend.api.routes_oxdna import router as oxdna_router


def test_cloud_routes_are_not_registered_but_trajectory_routes_remain():
    paths = {route.path for router in (md_router,oxdna_router) for route in router.routes}
    for engine in ('md','oxdna'):
        assert f'/{engine}/jobs/{{job_id}}/occupancy' not in paths
        assert f'/{engine}/jobs/{{job_id}}/occupancy-progress' not in paths
        assert any(path.startswith(f'/{engine}/jobs/') and '/trajectory' in path for path in paths)
