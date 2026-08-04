import random

from apigen_mt.domains.airline import AirlineDomainPlugin
from apigen_mt.domains.retail import RetailDomainPlugin


def test_retail_graph_has_no_domain_specific_leakage_in_algorithm():
    # graph.py must work identically for any DomainPlugin -- exercise both.
    from apigen_mt.graph import build_api_graph

    for plugin in (RetailDomainPlugin(), AirlineDomainPlugin()):
        g = build_api_graph(plugin)
        assert set(g.nodes) == {t.name for t in plugin.tools()}
        # every hand-annotated edge must be present
        for src, dst in plugin.api_graph_edges():
            assert dst in g.edges[src]


def test_retail_auto_inferred_edge_from_return_type_overlap(retail_plugin):
    g = retail_plugin.api_graph()
    # get_order_details returns Order (has product_id-bearing items), and
    # get_product_details consumes product_id -- but more directly:
    # find_user_id_by_email's name-token heuristic should produce 'user_id',
    # and get_user_details consumes 'user_id'.
    assert "get_user_details" in g.successors("find_user_id_by_email")


def test_random_walk_centers_on_write_tools(retail_plugin):
    g = retail_plugin.api_graph()
    rng = random.Random(42)
    write_names = {t.name for t in retail_plugin.write_tools()}
    for _ in range(20):
        seq = g.random_walk(rng, min_writes=1, max_writes=2, max_len=5)
        assert seq, "random walk should never be empty when write tools exist"
        assert any(name in write_names for name in seq)
        assert len(seq) <= 5


def test_airline_graph_builds_and_walks(airline_plugin):
    g = airline_plugin.api_graph()
    rng = random.Random(7)
    for _ in range(10):
        seq = g.random_walk(rng)
        assert seq
