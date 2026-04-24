# contracts/

Home for the message schemas between Nexus nodes.

Right now this directory is empty on purpose. The immediate decision on deck is the Jetson to 4070 transport (MQTT, ZeroMQ, REST, gRPC, all on the table per the handoff). Once that call is made, the message contract lives here as the canonical definition that both ends of the wire compile against.

Expected shape once populated:

```
contracts/
  jetson_to_brainstem/
    v1/
      event.proto   (or .json-schema, depending on transport)
      README.md
  brainstem_to_nas/
    v1/
      ...
```

Keep transport choice out of the schema layer. A schema describes what an event means, not how it moves.
