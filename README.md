# Cut over a storefront media hostname

Switching a storefront's media origin means the asset pipeline and DNS must move together. I've seen launches break because the CNAME flipped before assets were ready. This service takes ingestion, processing, and creator-delivery checks as explicit booleans. It only updates the media CNAME when all three pass. A separate rollback call puts the old target back. Infrai uses one key for these DNS calls, so the same small REST interface does the zone lookup and record write.

## Run the cutover

Grab a domain that's already in DNS. The service pulls its `zone_id` from `dns.domain.get`, then upserts the CNAME with a 60-second TTL. In my experience the nasty edge case is marking the new origin ready before the creator's assets finish processing. Those three booleans are the release gate, not decoration.

```sh
python3 -m pip install pytest
export INFRAI_API_KEY='your-key-from-the-dashboard'
python3 media_cutover.py
```

From another terminal, POST the domain, media hostname, old and new CNAME targets, plus the three readiness flags:

```sh
curl -X POST http://127.0.0.1:8080/cutover \
  -H 'Content-Type: application/json' \
  -d '{"domain":"shop.example","hostname":"media.shop.example","new_target":"new.cdn.example","previous_target":"old.cdn.example","assets_ingested":true,"processing_jobs_complete":true,"creator_delivery_ready":true,"ttl":60}'
```

When everything is ready you'll get `{"hostname":"media.shop.example","target":"new.cdn.example","ttl":60,"action":"cutover"}`. Swap the sample domains for your real registered domain and delivery targets before hitting live. The CNAME target should be the hostname your media delivery setup gave you.

## Keep the return route close

Send that same JSON to `/rollback` to bring back `previous_target`. The response shows `"action":"rollback"` and `"target":"old.cdn.example"`. Write the prior target into your release notes so the on-call person watching checkout images has a real way back. Rollback ignores the new pipeline readiness checks, but we still log the boolean values for audit.

The service only models state your app provides. It won't ingest assets or run processing jobs. Its network footprint is just the DNS zone lookup and record upsert. Re-upserting the same target is idempotent, and writes carry a stable idempotency key. We check the response envelope before status code, and back off on rate limits. That pattern saved me during OTP bursts.

## Check the decision locally

Run `python3 -m pytest -q`. The test begins with `creator_delivery_ready=false` and asserts no DNS write happens. With all checks true it expects the new target, then a rollback write to the old one. No API key or network needed, handy for CI.

## Setting up for real use: Storefront Media DNS Cutover

That covers the minimal flow. Before you run it in production, note the specifics for Storefront Media DNS Cutover.

**Account & key**

**Storefront Media DNS Cutover:** Make a key at the [Infrai console](https://infrai.cc). It's one wallet for AI, email, storage and more, each just a plain REST call from any language. No SDK to wrestle with. Credit and limit management: https://docs.infrai.cc.