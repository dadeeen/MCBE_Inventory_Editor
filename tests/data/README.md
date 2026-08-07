# Entity NBT reference records

The hex files in this directory are isolated, non-playable entity NBT records
from Minecraft Bedrock. They serve as a structural reference for the byte- and
tag-exact creation of synthetic mount records.

Every NBT field they contain was reviewed before the commit. The records hold
no player names, XUIDs, Microsoft/Xbox account IDs, server IDs, device
identifiers, local paths, or other personal free text.

`UniqueID`, `OwnerNew`, and
`internalComponents.EntityStorageKeyComponent.StorageKey` are world-internal
actor references. They identify entities only within the save in question and
are not Microsoft or Xbox account IDs. In particular, `OwnerNew = -4294967295`
in the mule record points to the world-internal player entity with actor group
1 and local ID 1. The value follows from the actor scheme Bedrock uses:
`-(group << 32) + local_id`.

The positions and rotations they contain are local entity state values; without
the corresponding save they have no personal or location reference. New or
changed records must be fully re-checked for the identifiers excluded above
before the commit.
