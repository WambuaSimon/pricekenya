# Wiring `DATABASE_URL` via a Blueprint `fromDatabase` reference

Assessment for issue #71. Research + draft only — nothing here has been
applied to Render, and the branch must not be merged without the pre-flight
steps in [§6](#6-if-you-go-ahead).

Docs read on 2026-10-07: [Blueprints (IaC)](https://render.com/docs/infrastructure-as-code),
[Blueprint spec](https://render.com/docs/blueprint-spec),
[Database credentials](https://render.com/docs/postgresql-credentials),
[Create & connect](https://render.com/docs/postgresql-creating-connecting),
[Legacy instance types](https://render.com/docs/postgresql-legacy-instance-types).

---

## Recommendation

**GO on the env-var reference. NO-GO on the `databases:` block.**

The issue proposes two changes bundled as one: (a) an `envVars` entry using
`fromDatabase`, and (b) a root-level `databases:` block declaring the live
Postgres instance so the reference has something to point at.

(b) turns out to be unnecessary. The Blueprint spec is explicit:

> You can reference a service that is not defined in your Blueprint file, but
> that service must exist in your workspace. Otherwise, your Blueprint fails
> to sync.

That sentence sits in the *Referencing service properties* section, which
covers `fromService` and `fromDatabase` together. `pricekenya-postgres`
exists in the workspace. So the reference resolves without declaring the
database, and the entire adoption risk — immutable-field matching, plan-ID
ambiguity, `readReplicas`, the rotated credential — simply does not arise.

The draft `render.yaml` on this branch therefore contains **only** change (a).
Everything the issue wanted from (b) is already available; everything (b)
added was risk.

Caveat that caps the value of even the safe half: **this solves the Render
side only.** See [§2](#2-does-fromdatabase-yield-the-internal-or-external-string).

---

## 1. Can a Blueprint adopt existing resources, and what triggers an apply?

**Adoption: yes, by name, and it is opt-in.**

> You can add an existing Render resource to your Blueprint. To do so, add the
> resource's details to your Blueprint file as you would for a new resource.
> […] When you next sync your Blueprint, Render applies the new configuration
> to the existing resource. The resource retains any existing environment
> variable values that aren't overwritten by the Blueprint.

For databases specifically, matching is on `name`:

> If you add the name of an _existing_ instance to your Blueprint file, Render
> attempts to apply the Blueprint's configuration to that existing instance.

So adding a `databases:` block named `pricekenya-postgres` would **not**
create a second database — it would try to reconcile the live one. (Name-suffixing
to avoid collisions happens only when you create a *new* Blueprint from a file
that matches existing resources, which is not our case.) The risk is not
duplication; it is *modification*. See [§4](#4-does-adoption-risk-the-immutable-fields-or-the-rotated-credential).

Also worth recording, because it cuts the other way and is reassuring:

> Changes to a Blueprint never cause a resource to be deleted. If you remove a
> resource definition from your Blueprint file or even disconnect a Blueprint
> entirely, _all existing resources remain intact_.

**Apply trigger: a push to the linked branch that modifies the Blueprint file.**

> Each push to the linked branch that modifies your Blueprint file triggers a
> deploy of any added or modified resources.

> By default, Render automatically updates affected resources every time you
> push Blueprint changes to your linked branch. To instead control exactly
> when you sync a particular Blueprint, set **Auto Sync** to **No** on your
> Blueprint's Settings page […] You can then manually trigger a sync by
> clicking **Manual Sync** on your Blueprint's page.

So: **auto-sync on push is the default, and nothing in this repo has turned it
off.** Merging a `render.yaml` change to `main` applies it to live
infrastructure without a further click. This is distinct from the service's
own `autoDeploy: commit` (confirmed `"autoDeploy":"yes","autoDeployTrigger":"commit"`
via the API), which redeploys code on any push; Blueprint sync is the thing
that rewrites configuration.

One unverifiable item: the Render REST API's service object does not report
Blueprint membership, so I could not confirm read-only that `srv-d92iuda8qa3s73dgfilg`
is still attached to a Blueprint tracking this `render.yaml`. DEPLOY.md §2 says
it was created via **New → Blueprint**. If that link was since broken, the
change is inert rather than dangerous — but then it also does nothing, and you
should check the dashboard before assuming either.

## 2. Does `fromDatabase` yield the internal or external string?

**Internal (private network). There is no property that yields the external one.**

The spec's *Supported properties* table, in full for Postgres:

| Property | Doc text |
|---|---|
| `connectionString` | "Render Postgres and Key Value only. The URL for connecting to the datastore over the **private network**. For Render Postgres, has the format `postgresql://user:password@host:port/database`" |
| `connectionPoolString` | "Render Postgres only. The URL for connecting to the database through its managed connection pool (if enabled)." |
| `user` | "The name of the user for your PostgreSQL database." |
| `password` | "The password for your PostgreSQL database." |
| `database` | "The name of your database within the PostgreSQL instance" |

Plus `host`, `port`, `hostport` and `slug`, all of which the table restricts to
"Web services and private services only" / "Workflow services only" — not
Postgres. There is no `externalConnectionString`, no `internalConnectionString`,
and no external `host`. Render's model is that external details are read from
the dashboard, CLI (`render pg get --include-sensitive-connection-info`) or the
*Retrieve Postgres connection info* API endpoint — never injected by a
Blueprint.

And the internal URL is unusable from CI:

> To use the internal URL, your connecting service and your database must
> belong to the same account and region.

`.github/workflows/scrape.yml`, `sitemap.yml` and `reset-db.yml` all read
`${{ secrets.DATABASE_URL }}` and run on GitHub-hosted runners, which are
neither. The `dpg-*` internal host does not resolve for them — DEPLOY.md
already lists `could not translate host name "dpg-..."` as the symptom.

**Consequence: the GitHub Actions secret stays a literal external connection
string.** Measured against the three costs the issue opens with:

| Issue's stated cost | Resolved? |
|---|---|
| Rotation needs a human | **Partly.** The Render side becomes a Manual Sync click. The GitHub secret still needs `gh secret set` by hand. |
| Credential passes through whoever does the wiring | **Partly.** No longer needed for Render. Still needed, in full, for CI. |
| It can drift | **Yes, for Render.** The dashboard value is no longer hand-maintained. CI can still drift. |

This is the "halves the problem" the issue anticipated, and the half that
remains is the one that put a URL in a transcript — the external string is the
one a human or agent has to handle. The honest framing is that this change
removes a *duplicate* of the credential, not the credential.

Note also that the injected value is not live-updating:

> These environment variables update to match the current value of the
> referenced property on each Blueprint sync. They do not update immediately
> whenever that property changes.

## 3. `readReplicas`: omitted vs empty

Omission is safe and documented as such. This is a non-issue provided you do
not write the key.

> - If you omit this field, Render _preserves_ any existing read replicas for
>   the instance.
> - If you provide different `name` values from a database's existing read
>   replicas, Render creates a new replica for each new name and destroys any
>   existing replicas that don't match any provided name.
> - If you provide an empty list (e.g., `readReplicas: []`), Render destroys
>   any existing replicas and does _not_ create new replicas.

The issue's warning is accurate but, for us, moot twice over: the API reports
`"readReplicas":[]` (none exist, so even the destructive form would be a
no-op), and the recommended draft has no `databases:` block in which to write
the key at all.

## 4. Does adoption risk the immutable fields or the rotated credential?

This is where the `databases:` block fails, on three counts.

### 4a. `plan` has no safe value

The live instance reports `"plan":"basic_256mb"`. **That string does not appear
anywhere in Render's current documentation** — not in the Blueprint spec's
Postgres compute-plan table (which lists `free`, `0.1c-256mb`, `0.5c-1g`,
`1c-2g`, `1c-4g`, `2c-4g`, …), not on the compute-plans page, not on the legacy
instance types page. Every option is a guess:

- **Write `basic_256mb`** — an undocumented plan ID. May fail Blueprint
  validation (which blocks the whole sync, including the env-var change we
  actually want), or may be accepted and reinterpreted.
- **Write `0.1c-256mb`** — documented, and spec-identical (0.1 CPU / 256 MB).
  But "same specs" is not "same plan ID", and if Render treats this as a plan
  *change*, the legacy doc's one-way door applies: "You cannot move _back_ to
  a legacy instance type."
- **Omit it** — the field table says this is safe ("Render retains the current
  compute plan for an existing database"), but the IaC overview says the
  opposite for adopted resources: "Make sure to include all configuration
  options that are currently set for the resource in the Render Dashboard. […]
  If you omit some of these options, your Blueprint will use a default value
  that almost definitely differs from your service's existing configuration."

Two Render doc pages disagree, and the loser pays with a plan change on the
production database. (For what it's worth, `basic_256mb` is probably *not* a
legacy instance type — legacy types are named Starter/Standard/Pro/Pro Plus and
bundle fixed storage, where Starter is 256 MB RAM / 0.1 CPU with **1 GB** fixed
disk; ours has a separately-set 5 GB disk, so it is a flexible plan under older
ID naming. "Probably" is not a basis for touching it.)

`diskSizeGB: 5` inherits the same ambiguity, since the spec says it is "Not
valid for legacy instance types, which have a fixed disk size."

### 4b. A declared `user` fights the next rotation

`user` is immutable ("You can't modify this value after creation"), and the
live default user — `pricekenyapostgres_bqux_user`, confirmed via the API — was
generated by the 2026-10-04 rotation, not by any Blueprint. Pinning it in YAML
declares a value Render says cannot change, in a field whose entire purpose in
the rotation workflow *is* to change. Omitting it lands back in the §4a
omit-vs-default contradiction.

This also explains the NOLOGIN original user cleanly:

> Render never fully deletes your database's original user. If you "delete" the
> original user, Render actually deactivates it by revoking its login
> privileges. This is a safeguard to preserve database objects owned by the
> original user.

Which is exactly the state `pricekenya_postgres_user` is in — NOLOGIN, still
owning all 13 tables. **Pre-existing and unrelated to this change**, but worth
flagging separately: object ownership sits with a role nobody can log in as.

### 4c. The credential side is already handled, without a `databases:` block

The credentials doc is unambiguous that `fromDatabase` tracks the default user
automatically:

> The default user's credentials appear in your database's connection URLs
> shown in the Render Dashboard. Default user credentials are also used by
> environment variables that reference connection strings in a Render
> Blueprint. Whenever the default user changes, these environment variables
> update their value on the next Blueprint sync.

And the documented rotation procedure assumes precisely our setup:

> For Blueprint-managed services that dynamically reference the database's
> connection string, perform a manual Blueprint sync to update the environment
> variable.

So the rotation benefit comes from the **env-var reference alone**. The
`databases:` block contributes nothing to it. Every risk in §4a and §4b is
paid for zero return.

## 5. Residual risks of the recommended (env-var-only) change

Smaller, but not nil.

1. **The live `DATABASE_URL` value gets overwritten on the next sync.** Today
   it is a `sync: false` dashboard literal. After the change, Render computes
   it. "A Blueprint can create new environment variables or modify the values
   of existing ones." If the dashboard literal is *not* currently the internal
   URL of the current default user — e.g. someone pasted the external string —
   the app's connection path changes at sync. Expected to be a no-op; verify
   before syncing, don't assume.
2. **A sync applies the whole file, not just your diff.** Any drift between
   `render.yaml` and the live service's dashboard config gets reconciled in the
   same sync. Spot-checked against the API and nothing in `render.yaml`
   conflicts with live (`starter`, `frankfurt`, `python`, `/healthz`, 1
   instance, same build/start commands), and `render.yaml` has been this
   Blueprint's source since creation — so no *new* drift is introduced. Still
   read the sync diff rather than trusting this paragraph.
3. **`sync: false` prompting disappears for this key.** Worth knowing if the
   Blueprint is ever replicated to build a staging stack: that copy will point
   its `DATABASE_URL` at `pricekenya-postgres`, i.e. production, unless a
   `databases:` block is added to the *copy*.
4. **Auto-sync means merging is the apply.** There is no review step between
   `main` and live. That is the single biggest operational risk here and §6
   exists to defuse it.

## 6. If you go ahead

In order. Steps 1–3 and 5–6 are dashboard actions for a human — this branch
deliberately performed no Render writes.

1. **Confirm the Blueprint link.** Dashboard → Blueprints. Verify one exists,
   tracks this repo, branch `main`, path `render.yaml`, and lists
   `pricekenya`. If not, stop — the change would be inert.
2. **Set Auto Sync to No** on that Blueprint's Settings page. Do this *before*
   merging, so landing on `main` does not auto-apply.
3. **Record the current `DATABASE_URL`** from the web service's Environment tab
   (just enough to compare hosts and username — do not paste it anywhere
   persistent) and confirm it is the internal `dpg-db16ucegekts73cgbpt0-a` host
   with user `pricekenyapostgres_bqux_user`.
4. Merge this branch.
5. **Manual Sync**, and read the proposed-changes diff before confirming. It
   should list exactly one change: `DATABASE_URL` on `pricekenya`. If it
   mentions the database, any plan, any region, or any other service, cancel.
6. Verify `curl https://www.pricekenya.co.ke/healthz` → `ok`, and that the
   service's env var now shows as database-linked rather than a literal.
7. **Leave the GitHub Actions secret alone.** It is load-bearing and this
   change does not replace it. Consider a comment in `scrape.yml` recording
   why it must stay a literal.
8. Re-enable Auto Sync only if you want future `render.yaml` pushes to apply
   unreviewed. Given this repo's history of unattended-CI surprises
   (OPERATIONS.md §8s, §8w), leaving it off is the better default.

**Do not, at any point, add a `databases:` block.** If a future change needs
one — a staging environment, preview environments, read replicas — resolve the
`basic_256mb` plan-ID question with Render support first, and use
*Generate Blueprint* from the dashboard (which emits the live configuration
verbatim) rather than hand-writing the fields.

### The block that was rejected

Recorded so nobody re-derives it. **Do not commit this.**

```yaml
# NOT RECOMMENDED — see §4.
databases:
  - name: pricekenya-postgres
    plan: basic_256mb        # undocumented plan ID; see §4a
    region: frankfurt        # immutable
    postgresMajorVersion: "18"   # immutable
    databaseName: pricekenya_postgres  # immutable
    user: pricekenyapostgres_bqux_user # immutable; fights rotation, §4b
    diskSizeGB: 5            # increase-only; legacy ambiguity, §4a
    ipAllowList:
      - source: 0.0.0.0/0
    # readReplicas deliberately omitted — omission preserves, [] destroys (§3)
```

## Appendix: live state (read-only, 2026-10-07)

`GET /v1/postgres/dpg-db16ucegekts73cgbpt0-a`:

```
name pricekenya-postgres   region frankfurt   version 18   plan basic_256mb
databaseName pricekenya_postgres   databaseUser pricekenyapostgres_bqux_user
diskSizeGB 5   diskAutoscalingEnabled false   connectionPool none
readReplicas []   highAvailabilityEnabled false   ipAllowList [0.0.0.0/0]
status available   createdAt 2026-10-04T15:22:25Z
```

`GET /v1/services/srv-d92iuda8qa3s73dgfilg`:

```
name pricekenya   region frankfurt   plan starter   numInstances 1
runtime python   healthCheckPath /healthz   branch main
autoDeploy yes (trigger: commit)   previews off   pullRequestPreviews no
```
