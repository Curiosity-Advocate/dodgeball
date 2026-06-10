# C4 Diagrams

A C4 view of the system at increasing zoom: context, containers, and components,
plus a labelled future-state diagram. This is the visual companion to
[overview.md](../overview.md) §4.

## Level 1 — System Context

Who uses the system and why.

```mermaid
flowchart TB
    scorekeeper([Scorekeeper])
    admin([Admin])
    spectator([Spectator])
    system[[DodgeballPlus]]

    scorekeeper -->|publishes scoring events during a match| system
    admin -->|manages competitions, teams, matches, assignments| system
    system -->|pushes live updates| spectator
```

The scorekeeper writes, the admin sets things up, and spectators read. There are no
external systems in v1.0 — historical data sources arrive in v2.0.

## Level 2 — Container

The runtime shape: one application process and one database.

```mermaid
flowchart LR
    sk([Scorekeeper])
    ad([Admin])
    sp([Spectator])

    app["FastAPI app<br/>REST + WebSocket<br/>in-process fan-out"]
    db[("PostgreSQL<br/>event log + projections + accounts")]

    sk -->|POST scoring events REST| app
    ad -->|admin REST| app
    sp -->|WebSocket live + REST reads| app
    app -->|append, read, project| db
```

PostgreSQL is the single integration point. Fan-out to spectators happens
in-process inside the one instance (sufficient for the ~5,000-connection target).

## Level 3 — Component

Inside the application, organised by the business areas from overview §2.

```mermaid
flowchart TB
    client([Clients])

    subgraph app[FastAPI application]
        auth[Identity & Access]
        read[Read & Query]
        scoring[Live Scoring]
        es[EventStore]
        delivery[Real-time Delivery]
    end

    db[("PostgreSQL")]

    client -->|login / refresh| auth
    client -->|snapshot, replay, standings| read
    client -->|POST events| scoring
    client -. WebSocket .-> delivery

    auth --> db
    read --> db
    scoring --> es
    es -->|append event + update projections| db
    es -->|new event| delivery
```

The `EventStore` is the only path to the event log: `Live Scoring` appends through
it, it updates the projections, and it hands the new event to `Real-time Delivery`
for fan-out. `Read & Query` and `Identity & Access` talk to PostgreSQL directly.

## Future state (not built in v1.0)

The horizontal-scaling shape, shown for context only. Pursued only when measurement
justifies it (`NFR-4`); the WebSocket gateway is where the specialist runtime from
ADR-0009 would slot in.

```mermaid
flowchart LR
    clients([Clients])
    lb{{Load balancer}}
    api["API service<br/>REST"]
    gw["WebSocket gateway<br/>fan-out (specialist runtime)"]
    worker["Worker<br/>projections, scraping, CV"]
    bus[["Event stream / broker"]]
    db[("PostgreSQL")]

    clients --> lb
    lb --> api
    lb --> gw
    api -->|append| db
    api -->|publish| bus
    bus --> gw
    bus --> worker
    worker --> db
```
