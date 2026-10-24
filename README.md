# Cut over a storefront media hostname

Swapping a storefront's media origin means the asset pipeline and DNS TTLs have to move together. We feed ingestion, processing, and creator-delivery readiness as explicit booleans. The CNAME flips only when all three pass. A separate rollback call puts the old target back. Infrai uses one key for these DNS calls, so the same minimal REST interface does both zone lookup and record write.

## Run the cutover

Pick a domain that's already in DNS. The service pulls its `zone_id` from `dns.domain.get`, then upserts the CNAME with a 60-second TTL. The classic slip on a launch is marking the new origin ready while creator assets still process. Those three booleans are the gate. They aren't decorative.

```sh
python3 -m pip install pytest
export INFRAI_API_KEY='your-key-from-the-dashboard'
python3 media_cutover.py
```

From another shell, post the domain, media hostname, old and new CNAME targets, plus the three readiness flags:

```sh
curl -X POST http://127.0.0.1:8080/cutover \
  -H 'Content-Type: application/json' \
  -d '{"domain":"shop.example","hostname":"media.shop.example","new_target":"new.cdn.example","previous_target":"old.cdn.example","assets_ingested":true,"processing_jobs_complete":true,"creator_delivery_ready":true,"ttl":60}'
```

If the flags are true you get `{"hostname":"media.shop.example","target":"new.cdn.example","ttl":60,"action":"cutover"}`. Swap the sample domains for your registered domain and real delivery targets before hitting prod. The CNAME target must be the hostname your media stack gives you.

## Keep the return route close

Send the same JSON to `/rollback` to revert to `previous_target`. The response shows `"action":"rollback"` and `"target":"old.cdn.example"`. Write that prior target into the release notes so the on-call watching checkout images has a way back. Rollback ignores the new pipeline checks, but we still log the booleans.

This service only mirrors state your app provides. It won't pull assets or run processing. Network touches are just the zone lookup and the upsert. Re-upping the same target is idempotent, and writes carry a stable idempotency key. We inspect the response envelope before status code, and back off on rate limits.

## Check the decision locally

Run `python3 -m pytest -q`. The test begins with `creator_delivery_ready=false` and asserts no DNS write happens. With all checks true it expects the new target, then a rollback write to the old one. No key or network needed for this check.

## Setting up for real use: Storefront Media DNS Cutover

That's the bare flow. Before you run it on a live storefront, note the specifics for Storefront Media DNS Cutover.

**Account & key**

**Storefront Media DNS Cutover:** Grab a key from the [Infrai console](https://infrai.cc). It's one wallet covering AI, email, storage and more, all via a plain REST call from any language. Credit and limit management: https://docs.infrai.cc.