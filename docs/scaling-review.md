# Cost and scaling review

Blueprint step 61: costs, scaling limits and the deferred list, to plan the next release. Written in November 2026.
**Nothing here has run on AWS or under real load,** so the AWS costs are rough estimates to check against current
pricing, and the limits are judgements from how the system is built, not load test results.

## What's built

Phases 1–10 run on one PC with Docker. The checklist steps not done are AWS provisioning, the staging test and launch
(39–42), and collaborative filtering (51), which the blueprint says to wait on.

## Costs

| Setup | Rough cost a month | Notes |
|---|---|---|
| Your own PC | Electricity only | Not public: only you can use it |
| Core site on AWS, as in the [runbook](runbook.md) | About $310, before traffic | Staging is about half. CloudFront and S3 grow with viewers and videos |
| Adding the data stack and big data stack on AWS | Not estimated | No Terraform yet. Needs at least one more server with 8 GB or more of memory |

**What will cost the most as you grow:**

1. **Video delivery.** CloudFront charges for data sent. It grows with watch time, and is usually the first big bill for
   a video site.
2. **Encoding.** One encoder handles one video at a time, so a queue of long videos needs more machines.
3. **Storage.** Each video is stored as the original plus up to three renditions. The lifecycle rule moves originals to
   cheaper storage after 30 days.
4. **Always-on services.** Kafka, the database and the servers cost the same with no viewers at all.

## Scaling limits

Roughly in the order you'd reach them:

| Part | Limit | What to do |
|---|---|---|
| Encoding | Videos wait in line behind one encoder | Add encoders: `--scale encoder=N` locally, more hosts on AWS. Topics have 6 partitions, so up to 6 |
| Search | The search document is built for every query, so it slows as the catalogue grows | Store a `tsvector` with a GIN index. OpenSearch only when that isn't enough |
| API | 3 web workers on one host | More workers, then more hosts behind the load balancer. Then a shared cache for the throttle counts |
| ML worker | CPU only: about 13× real time for speech on 2 cores in testing, so videos queue up | Run on a GPU host, as the blueprint suggests |
| MongoDB | Raw events grow fast, but expire after 90 days | Keep the expiry. The lake holds the long-term history |
| Nightly pandas job | Loads a whole day into memory | Switch to `ANALYTICS_ENGINE=spark`. The blueprint's trigger is tens of millions of events |
| Spark | Runs in one container (`local[2]`) | A real cluster, or a managed one such as EMR |
| Local CDN stand-in | A small Python server, only for development | Use real CloudFront in production. It's already written in Terraform |
| Single database | One PostgreSQL holds the app and analytics | Read replica, then a separate analytics database |

## Deferred, and when to reconsider

| Item | Reconsider when |
|---|---|
| Collaborative filtering and MLflow (step 51) | A few thousand users have real watch history |
| Comments | You want viewers to comment and have a moderation plan |
| Dedicated content moderation | Before accepting public uploads. CLIP flags were only tested for false alarms and on one weapon photo |
| Jupyter container | Someone is actually exploring the data |
| Monitoring for encoding failure rate, API latency and cache hit ratio | When setting up AWS |
| Flink | Real-time features become central to the product |
| Schema registry | Several teams depend on the event formats |
| 4K, AV1 and per-title encoding | Streaming-quality data shows they'd pay off |
| Encoder autoscaling on ECS or Kubernetes | Uploads regularly wait too long |
| WebSockets instead of polling | Polling load becomes a problem |
| DRM | Licensed content requires it |

## Suggested next steps

1. **Use it with real videos and viewers.** Everything measured so far is from small samples and demo data. Real usage
   will show which limit matters first, and the similar-videos cutoff still needs measuring on real content.
2. **Sort out hosting.** AWS is what's written, and needs a card and a budget. Pick a size only after step 1.
3. **Plan moderation and write a privacy policy before opening uploads to the public.**
4. **Leave the big data stack off until it's needed.** It's working and tested, but pandas is enough at this size, and
   the extra services cost memory locally and money in the cloud.
