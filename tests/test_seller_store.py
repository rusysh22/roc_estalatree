"""Seller store-block management: reorder + inline visibility toggle."""
import uuid

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import SellerProfile
from apps.storefront.models import Block
from tests.factories import PlanFactory, ProductFactory, UserFactory


def _seller(name="Blocks Store"):
    sfx = uuid.uuid4().hex[:8]
    return SellerProfile.objects.create(
        name=name, slug=f"store-{sfx}", is_approved=True,
        onboarding_completed=True, user=UserFactory(),
    )


@pytest.fixture
def seller_with_blocks(db):
    seller = _seller()
    store = seller.store_page  # auto-created by post_save signal
    store.is_published = True
    store.save(update_fields=["is_published"])
    blocks = []
    for i in range(4):
        p = ProductFactory(seller=seller, slug=f"bp-{uuid.uuid4().hex[:8]}", name=f"BP {i}")
        PlanFactory(product=p, seller=seller)
        blocks.append(Block.objects.create(store_page=store, product=p,
                                           type=Block.Type.PRODUCT, position=i + 1))
    return seller, store, blocks


def _client(seller):
    c = Client()
    c.force_login(seller.user)
    return c


@pytest.mark.django_db
def test_reorder_persists_new_positions(seller_with_blocks):
    seller, store, blocks = seller_with_blocks
    c = _client(seller)
    new_order = [blocks[3].pk, blocks[0].pk, blocks[2].pk, blocks[1].pk]
    resp = c.post(reverse("seller:block_reorder"),
                  {"order": ",".join(map(str, new_order))},
                  HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    positions = {b.pk: b.position for b in Block.objects.filter(store_page=store)}
    assert [positions[pk] for pk in new_order] == [1, 2, 3, 4]


@pytest.mark.django_db
def test_reorder_rejects_incomplete_list(seller_with_blocks):
    seller, store, blocks = seller_with_blocks
    c = _client(seller)
    resp = c.post(reverse("seller:block_reorder"),
                  {"order": f"{blocks[0].pk},{blocks[1].pk}"},
                  HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_reorder_rejects_foreign_blocks(seller_with_blocks):
    seller, store, blocks = seller_with_blocks
    other = _seller("X")
    ostore = other.store_page
    op = ProductFactory(seller=other, slug=f"xp-{uuid.uuid4().hex[:8]}")
    oblock = Block.objects.create(store_page=ostore, product=op, type=Block.Type.PRODUCT)
    c = _client(seller)
    ids = [b.pk for b in blocks] + [oblock.pk]
    resp = c.post(reverse("seller:block_reorder"), {"order": ",".join(map(str, ids))},
                  HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_toggle_visibility_ajax_returns_json(seller_with_blocks):
    seller, store, blocks = seller_with_blocks
    c = _client(seller)
    url = reverse("seller:block_toggle_visibility", args=[blocks[0].pk])
    resp = c.post(url, {}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert resp.json() == {"is_visible": False}
    blocks[0].refresh_from_db()
    assert blocks[0].is_visible is False


@pytest.mark.django_db
def test_toggle_visibility_plain_post_still_redirects(seller_with_blocks):
    seller, store, blocks = seller_with_blocks
    c = _client(seller)
    url = reverse("seller:block_toggle_visibility", args=[blocks[0].pk])
    resp = c.post(url, {})
    assert resp.status_code == 302


@pytest.mark.django_db
def test_store_page_renders_filter_when_many_blocks(seller_with_blocks):
    seller, store, blocks = seller_with_blocks
    # 4 blocks -> no filter; add 3 more to cross the >6 threshold
    for i in range(4, 8):
        p = ProductFactory(seller=seller, slug=f"bp-{uuid.uuid4().hex[:8]}", name=f"BP {i}")
        Block.objects.create(store_page=store, product=p, type=Block.Type.PRODUCT, position=i + 1)
    resp = _client(seller).get(reverse("seller:store"))
    assert resp.status_code == 200
    assert b"data-block-filter" in resp.content
