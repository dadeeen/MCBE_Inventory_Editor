"""Synthetic corruption checks; only an actual client/BDS run proves gameplay."""

from copy import deepcopy
import json
import struct

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from scripts.engine_checks import village_worker as worker
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.village_profile import ROLES, make_village_plan, validate_village_events, validate_village_plan
from tests.test_engine_villagers import synthetic_records


def village_events(phase="seed"):
    plan = make_village_plan()
    number = {"seed": 0, "reload1": 1, "reload2": 2}[phase]
    actors = {}
    for index, role in enumerate(ROLES):
        health = (6, 20) if role == "injured" and not number else (40, 40) if role == "injured" else (20, 20)
        items = [None] * 8
        if role == "farmer" and number:
            items[0] = {"name": "minecraft:carrot", "count": 3 + number}
        actors[role] = {
            "identity": str(index + 1),
            "type": "minecraft:villager_v2",
            "current": health[0],
            "maximum": health[1],
            "variant": 1 if role == "farmer" else 0,
            "items": items,
        }
    before_player = {"emerald": 64 - number, "bread": 6 * number, "carrot": 8 - number}
    trade_player = {**before_player, "emerald": before_player["emerald"] - 1, "bread": before_player["bread"] + 6}
    after_player = {**trade_player, "carrot": trade_player["carrot"] - 1}
    after_actors = deepcopy(actors)
    carrot_before = 3 + number if number else 0
    after_actors["farmer"]["items"][0] = {"name": "minecraft:carrot", "count": carrot_before + 1}
    cases = []
    if not number:
        cases.append(
            (
                "origin",
                {
                    "seed": plan["seed"],
                    "center": plan["center"],
                    "landmarks": plan["landmarks"],
                    "natural_residents": 6,
                    "actors": {
                        role: {
                            "identity": actor["identity"],
                            "type": actor["type"],
                            "variant": actor["variant"],
                            "position": plan["center"],
                            "original_name": "",
                        }
                        for role, actor in actors.items()
                    },
                },
            )
        )
    cases.extend(
        [
            ("before", {"actors": actors, "player": before_player}),
            ("trade", {"interactions": 1, "before": before_player, "after": trade_player}),
            (
                "pickup",
                {
                    "sources": [{"identity": "client-carrot-" + phase, "spawned": 1, "attempted": 1, "player_distance": 1.0}],
                    "picked_up": 1,
                    "farmer_before": carrot_before,
                    "farmer_after": carrot_before + 1,
                    "player_before": trade_player["carrot"],
                    "player_after": after_player["carrot"],
                },
            ),
            ("after", {"actors": after_actors, "player": after_player}),
            (
                "chunk_reload",
                {
                    "unloaded": True,
                    "actors": after_actors,
                    "chunks": [{"role": role, "position": plan["center"], "before": True, "away": False, "returned": True} for role in ROLES]
                    + [
                        {"role": "landmark_" + str(index), "position": marker["position"], "before": True, "away": False, "returned": True}
                        for index, marker in enumerate(plan["landmarks"])
                    ],
                },
            ),
        ]
    )
    return [{"kind": "case", "case_id": key, "snapshot": deepcopy(value)} for key, value in cases]


@pytest.mark.parametrize("phase", ["seed", "reload1", "reload2"])
def test_complete_live_natural_gameplay_is_required(phase):
    result = validate_village_events(village_events(phase), make_village_plan(), phase=phase)
    assert result["status"] == "pass"
    assert set(result["observations"]) == {"before", "trade", "pickup", "after", "chunk_reload"} | ({"origin"} if phase == "seed" else set())


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "reordered",
        "no_interaction",
        "no_payment",
        "no_bread",
        "no_drop",
        "no_pickup",
        "no_transfer",
        "no_unload",
        "wrong_identity",
        "health",
        "bool_health",
        "supplies",
        "landmark",
        "invented_actor",
        "not_natural",
    ],
)
def test_live_evidence_cannot_pass_without_all_independent_observations(fault):
    events = village_events()
    by_id = {event["case_id"]: event["snapshot"] for event in events}
    if fault == "missing":
        events.pop()
    elif fault == "duplicate":
        events.append(deepcopy(events[-1]))
    elif fault == "reordered":
        events.reverse()
    elif fault == "no_interaction":
        by_id["trade"]["interactions"] = 0
    elif fault == "no_payment":
        by_id["trade"]["after"]["emerald"] = 64
    elif fault == "no_bread":
        by_id["trade"]["after"]["bread"] = 0
    elif fault == "no_drop":
        by_id["pickup"]["sources"] = []
    elif fault == "no_pickup":
        by_id["pickup"]["picked_up"] = 0
    elif fault == "no_transfer":
        by_id["pickup"]["farmer_after"] = 0
    elif fault == "no_unload":
        by_id["chunk_reload"]["unloaded"] = False
    elif fault == "wrong_identity":
        by_id["chunk_reload"]["actors"]["farmer"]["identity"] = "replacement"
    elif fault in {"health", "bool_health"}:
        by_id["after"]["actors"]["injured"]["current"] = True if fault == "bool_health" else 7
    elif fault == "supplies":
        by_id["after"]["actors"]["farmer"]["items"][0]["count"] = True
    elif fault == "landmark":
        by_id["origin"]["landmarks"] = []
    elif fault == "invented_actor":
        by_id["origin"]["actors"]["farmer"]["identity"] = "not-observed"
    else:
        by_id["origin"]["actors"]["farmer"]["original_name"] = "Preexisting named villager"
    with pytest.raises(ProbeError):
        validate_village_events(events, make_village_plan(), phase="seed")


@pytest.mark.parametrize("fault", ["seed", "center", "names", "landmarks", "format", "trade", "booths", "workstation"])
def test_plan_is_bound_to_measured_natural_generation(fault):
    plan = make_village_plan()
    plan.pop(fault)
    with pytest.raises(ProbeError):
        validate_village_plan(plan)


@pytest.mark.parametrize(
    ("field", "value"),
    [("identity", ""), ("spawned", 0), ("spawned", True), ("attempted", 0), ("attempted", 2), ("player_distance", 5), ("player_distance", float("nan"))],
)
def test_pickup_requires_a_matching_native_item_from_the_client(field, value):
    events = village_events()
    pickup = next(event["snapshot"] for event in events if event["case_id"] == "pickup")
    pickup["sources"][0][field] = value
    with pytest.raises(ProbeError):
        validate_village_events(events, make_village_plan(), phase="seed")


def test_trade_gui_currency_is_not_a_completed_payment():
    events = village_events()
    next(event["snapshot"] for event in events if event["case_id"] == "trade")["after"]["emerald"] = 0
    with pytest.raises(ProbeError, match="GUI-held currency"):
        validate_village_events(events, make_village_plan(), phase="seed")


def test_farmer_can_harvest_wheat_without_losing_the_tested_carrots():
    events = village_events()
    reloaded = next(event["snapshot"] for event in events if event["case_id"] == "chunk_reload")
    reloaded["actors"]["farmer"]["items"][1] = {"name": "minecraft:wheat", "count": 3}
    assert validate_village_events(events, make_village_plan(), phase="seed")["status"] == "pass"
    reloaded["actors"]["farmer"]["items"][0] = None
    with pytest.raises(ProbeError):
        validate_village_events(events, make_village_plan(), phase="seed")


@pytest.mark.parametrize("variants", [[1, 0, 0], [5, 7, 12]])
def test_missing_native_professions_cannot_start_gameplay(variants):
    from tests.node_runner import run_node

    run_node(
        "const plan="
        + json.dumps(make_village_plan())
        + ";const variants="
        + json.dumps(variants)
        + ";\n"
        + r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync('scripts/engine_checks/pack/scripts/village.js','utf8').replace(/^import .*;\s*/m,'').replace('export function* ','function* ');
const actors=variants.map((variant,index)=>({id:String(index),typeId:'minecraft:villager_v2',
 getComponent:id=>id==='minecraft:variant'?{value:variant}:undefined}));
const settle=new Function(source+';return settleProfessions;')();
const task=settle(actors);
assert.throws(()=>{for(let i=0;i<2500;i++)assert.equal(task.next().done,false);},/two settled adult controls/);
"""
    )


def test_seed_invites_client_only_after_natural_residents_and_booths_are_ready():
    from tests.node_runner import run_node

    run_node(
        "const plan="
        + json.dumps(make_village_plan())
        + ";\n"
        + r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync('scripts/engine_checks/pack/scripts/village.js','utf8').replace(/^import .*;\s*/m,'').replace('export function* ','function* ');
let placed=0,invited=false;
const actors=[0,0,0].map((variant,index)=>({id:String(index),typeId:'minecraft:villager_v2',nameTag:'',location:{...plan.center},
 teleport(p){this.location=p;},getComponent:id=>id==='minecraft:variant'?{value:variant}:
 id==='minecraft:health'?{setCurrentValue:()=>assert.fail('Do not seed injury before native job selection')}:undefined}));
const dimension={isChunkLoaded:()=>true,getEntities:()=>actors,runCommand:()=>{},getBlock:p=>({isAir:true,
 typeId:plan.landmarks.find(m=>JSON.stringify(m.position)===JSON.stringify(p))?.type,setType:()=>placed++})};
const world={seed:plan.seed,getDimension:()=>dimension,getAllPlayers:()=>{assert.ok(invited);return [];},
 tickingAreaManager:{createTickingArea:()=>({then:resolve=>resolve()})}};
const probe=new Function('GameMode','ItemStack','world',source+';return villageRoundtrip;')({},()=>assert.fail('No client supplies yet'),world);
const task=probe({phase:'seed',village_profile:plan},(kind,fields)=>{
 assert.notEqual(fields.case_id,'origin','Role selection waits for the real client and native jobs');
 if(fields.stage==='waiting_for_client'){
  assert.ok(placed>0);assert.ok(actors.every(e=>e.location.y===96&&e.nameTag===''));invited=true;
 }
});
for(let i=0;i<160;i++)assert.equal(task.next().done,false);
assert.ok(invited);
"""
    )


@pytest.mark.parametrize("occupied", [False, True])
def test_interaction_booths_preserve_natural_actors_and_check_all_space_before_writing(occupied):
    from tests.node_runner import run_node

    run_node(
        "const plan="
        + json.dumps(make_village_plan())
        + ";const occupied="
        + json.dumps(occupied)
        + ";\n"
        + r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync('scripts/engine_checks/pack/scripts/village.js','utf8').replace(/^import .*;\s*/m,'').replace('export function* ','function* ');
const writes=[],moves=[],reads=new Set(),key=p=>JSON.stringify(p);
const last=plan.booths.control, obstacle={x:last.x+3,y:last.y+3,z:last.z+3};
const dimension={getBlock:p=>{reads.add(key(p));return {isAir:!occupied||key(p)!==key(obstacle),
 setType:type=>writes.push({p,type})};}};
const actors=Object.fromEntries(Object.entries(plan.names).map(([role,name])=>[role,{id:name,
 teleport:(p,options)=>{assert.equal(options.dimension,dimension);moves.push({role,p});}}]));
const build=new Function(source+';return prepareBooths;')();
const task=build(dimension,plan,actors),run=()=>{while(!task.next().done){}};
if(occupied){assert.throws(run,/footprint is not empty/);assert.equal(writes.length,0);assert.equal(moves.length,0);}
else{
 run();assert.equal(reads.size,3*7*7*5);assert.equal(writes.length,3*(7*7*2+24*3+1));assert.equal(moves.length,3);
 for(const {role,p} of moves){const center=plan.booths[role];
  assert.deepEqual(p,{x:center.x+.5,y:center.y,z:center.z+.5});assert.equal(actors[role].id,plan.names[role]);}
 for(const {p,type} of writes){const center=Object.values(plan.booths).find(c=>Math.abs(p.x-c.x)<=3&&Math.abs(p.z-c.z)<=3);
  assert.ok(center);
  if(type===plan.workstation){assert.deepEqual(p,{x:center.x+2,y:center.y,z:center.z+2});continue;}
  assert.ok(p.y===center.y-1||p.y===center.y+3||Math.abs(p.x-center.x)===3||Math.abs(p.z-center.z)===3);
  assert.equal(type,p.y===center.y-1?'minecraft:stone':'minecraft:glass');}
}
"""
    )


@pytest.mark.parametrize("obstruction", [None, "missing_floor", "blocked_interior", "escaped_farmer"])
def test_player_placement_requires_a_safe_booth_interior_even_with_fractional_actor_heights(obstruction):
    from tests.node_runner import run_node

    run_node(
        "const plan="
        + json.dumps(make_village_plan())
        + ";const obstruction="
        + json.dumps(obstruction)
        + ";\n"
        + r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync('scripts/engine_checks/pack/scripts/village.js','utf8').replace(/^import .*;\s*/m,'').replace('export function* ','function* ');
const place=new Function(source+';return faceFarmer;')();
for(const center of Object.values(plan.booths))for(const dx of [-1.7,-.5,.5,1.5,2.7])for(const dz of [-1.7,-.5,.5,1.5,2.7]){
 for(const dy of [-.000008,0,.875,1,1.25]){
  let teleports=0;
  const dimension={getBlock:p=>{
   assert.ok(Object.values(p).every(Number.isInteger),'Block queries must use integer coordinates');
   const floor=p.y===center.y-1,wall=Math.abs(p.x-center.x)===3||Math.abs(p.z-center.z)===3;
   const workstation=p.x===center.x+2&&p.z===center.z+2&&p.y===center.y;
   return {isAir:!floor&&!wall&&!workstation&&obstruction!=='blocked_interior',
    typeId:floor&&obstruction!=='missing_floor'?'minecraft:stone':'minecraft:air'};
  }};
  const farmer={dimension,location:{x:center.x+dx,y:center.y+dy,z:center.z+dz}};
  if(obstruction==='escaped_farmer')farmer.location.y=64;
  const player={teleport:(p,options)=>{
   teleports++;assert.equal(options.dimension,dimension);assert.equal(p.y,center.y+.1);
   assert.ok(p.x-.3>=center.x-2&&p.x+.3<=center.x+3&&p.z-.3>=center.z-2&&p.z+.3<=center.z+3);
   assert.ok(Math.hypot(p.x-farmer.location.x,p.z-farmer.location.z)>=1.25);
   assert.notDeepEqual([Math.floor(p.x),Math.floor(p.z)],[center.x+2,center.z+2]);
  }};
  if(obstruction){assert.throws(()=>place(player,farmer,plan),/No safe player position|outside its interaction booth/);assert.equal(teleports,0);}
  else {place(player,farmer,plan);assert.equal(teleports,1);}
 }
}
"""
    )


def _offer(uses=1, count=6, experience=2):
    return nbt.CompoundTag(
        {
            "Variant": nbt.IntTag(1),
            "TradeExperience": nbt.IntTag(experience),
            "Offers": nbt.CompoundTag(
                {
                    "Recipes": nbt.ListTag(
                        [
                            nbt.CompoundTag(
                                {
                                    "buyA": nbt.CompoundTag({"Name": nbt.StringTag("minecraft:emerald"), "Count": nbt.ByteTag(1)}),
                                    "sell": nbt.CompoundTag({"Name": nbt.StringTag("minecraft:bread"), "Count": nbt.ByteTag(count)}),
                                    "uses": nbt.IntTag(uses),
                                    "traderExp": nbt.IntTag(2),
                                }
                            )
                        ]
                    )
                }
            ),
        }
    )


@pytest.mark.parametrize("fault", ["extra_use", "no_experience", "wrong_count", "no_offer", "duplicate_offer", "wrong_profession", "bool_use", "wrong_xp"])
def test_client_delta_alone_cannot_prove_a_native_trade(fault):
    root = _offer()
    if fault == "extra_use":
        root["Offers"]["Recipes"][0]["uses"] = nbt.IntTag(2)
    elif fault == "no_experience":
        root["TradeExperience"] = nbt.IntTag(0)
    elif fault == "wrong_count":
        root["Offers"]["Recipes"][0]["sell"]["Count"] = nbt.ByteTag(5)
    elif fault == "no_offer":
        root["Offers"]["Recipes"] = nbt.ListTag([], list_data_type=10)
    elif fault == "duplicate_offer":
        recipe = root["Offers"]["Recipes"][0]
        root["Offers"]["Recipes"] = nbt.ListTag([recipe, deepcopy(recipe)])
    elif fault == "wrong_profession":
        root["Variant"] = nbt.IntTag(2)
    elif fault == "wrong_xp":
        root["TradeExperience"] = nbt.IntTag(3)
    else:
        root["Offers"]["Recipes"][0]["uses"] = nbt.ByteTag(1)
    evidence = validate_village_events(village_events(), make_village_plan(), phase="seed")["observations"]
    with pytest.raises(ProbeError):
        worker.verify_native_trade(worker.trade_snapshot(root), None, evidence)


def test_saved_trade_must_increase_again_after_every_restart():
    evidence = validate_village_events(village_events("reload1"), make_village_plan(), phase="reload1")["observations"]
    previous = worker.trade_snapshot(_offer())
    with pytest.raises(ProbeError):
        worker.verify_native_trade(previous, previous, evidence)
    worker.verify_native_trade(worker.trade_snapshot(_offer(uses=2, experience=4)), previous, evidence)


@pytest.mark.parametrize("uses", [0, 1])
def test_native_restock_can_reset_usage_but_requires_exact_recipe_experience(uses):
    evidence = validate_village_events(village_events("reload1"), make_village_plan(), phase="reload1")["observations"]
    previous = worker.trade_snapshot(_offer())
    current = worker.trade_snapshot(_offer(uses=uses, experience=4))
    worker.verify_native_trade(current, previous, evidence)
    current["experience"] = 5
    with pytest.raises(ProbeError, match="single saved native trade"):
        worker.verify_native_trade(current, previous, evidence)


@pytest.mark.parametrize("experience", [None, nbt.ByteTag(2), nbt.IntTag(0)])
def test_native_recipe_experience_requires_a_positive_typed_value(experience):
    root = _offer()
    recipe = root["Offers"]["Recipes"][0]
    if experience is None:
        recipe.pop("traderExp")
    else:
        recipe["traderExp"] = experience
    with pytest.raises(ProbeError, match="offer experience"):
        worker.trade_snapshot(root)


@pytest.mark.parametrize("uses,bread", [(2, 6), (2, 12), (1, 12)])
def test_native_trade_counter_is_exactly_one_per_phase(uses, bread):
    evidence = validate_village_events(village_events(), make_village_plan(), phase="seed")["observations"]
    evidence["trade"]["after"]["bread"] = bread
    with pytest.raises(ProbeError):
        worker.verify_native_trade(worker.trade_snapshot(_offer(uses=uses)), None, evidence)


@pytest.mark.parametrize("fault", ["farmer_before", "farmer_after", "chunk_food_loss", "control_items", "farmer_profession", "injured_items"])
def test_live_counts_controls_and_chunk_persistence_are_cross_checked(fault):
    events = village_events()
    by_id = {event["case_id"]: event["snapshot"] for event in events}
    if fault in {"farmer_before", "farmer_after"}:
        # Keep all claimed drop counters mutually consistent; alter only the
        # independently captured real actor slots.
        stage = "before" if fault == "farmer_before" else "after"
        by_id[stage]["actors"]["farmer"]["items"] = [None] * 8
        if stage == "before":
            by_id[stage]["actors"]["farmer"]["items"][0] = {"name": "minecraft:carrot", "count": 3}
        else:
            by_id["chunk_reload"]["actors"]["farmer"]["items"] = [None] * 8
    elif fault == "chunk_food_loss":
        by_id["chunk_reload"]["actors"]["farmer"]["items"] = [None] * 8
    elif fault == "farmer_profession":
        by_id["after"]["actors"]["farmer"]["variant"] = 5
        by_id["chunk_reload"]["actors"]["farmer"]["variant"] = 5
    else:
        role = "control" if fault == "control_items" else "injured"
        for stage in ("after", "chunk_reload"):
            by_id[stage]["actors"][role]["items"][0] = {"name": "minecraft:carrot", "count": 1}
    with pytest.raises(ProbeError):
        validate_village_events(events, make_village_plan(), phase="seed")


@pytest.mark.parametrize("fault", ["missing", "duplicate", "initially_unloaded", "stayed_loaded", "not_reloaded", "wrong_landmark", "numeric_boolean"])
def test_native_chunk_evidence_requires_all_actor_and_landmark_transitions(fault):
    events = village_events()
    chunks = events[-1]["snapshot"]["chunks"]
    if fault == "missing":
        chunks.pop()
    elif fault == "duplicate":
        chunks[-1] = deepcopy(chunks[-2])
    elif fault == "initially_unloaded":
        chunks[0]["before"] = False
    elif fault == "stayed_loaded":
        chunks[1]["away"] = True
    elif fault == "not_reloaded":
        chunks[2]["returned"] = False
    elif fault == "numeric_boolean":
        chunks[0]["before"] = 1
    else:
        chunks[-1]["position"] = make_village_plan()["center"]
    with pytest.raises(ProbeError):
        validate_village_events(events, make_village_plan(), phase="seed")


def _records(phase="seed"):
    plan = make_village_plan()
    evidence = validate_village_events(village_events(phase), plan, phase=phase)["observations"]
    actors = evidence["chunk_reload"]["actors"]
    records = synthetic_records([{"name": plan["names"][role], "seed": {**actors[role], "name": plan["names"][role]}} for role in ROLES], tagged=False)
    for index, role in enumerate(ROLES):
        key = b"actorprefix" + struct.pack("<Q", index + 1)
        named = load_player_nbt(records[key])
        named.tag["Variant"] = nbt.IntTag(1 if role == "farmer" else 0)
        if role == "farmer":
            number = {"seed": 1, "reload1": 2, "reload2": 3}[phase]
            named.tag.update(_offer(uses=number, experience=number * 2))
        records[key] = save_player_nbt(named)
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag(
                [
                    nbt.CompoundTag(
                        {"Slot": nbt.ByteTag(slot), "Name": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(count), "Damage": nbt.ShortTag(0)}
                    )
                    for slot, (name, count) in enumerate(evidence["after"]["player"].items())
                ]
            )
        }
    )
    records[b"player_server_synthetic"] = save_player_nbt(nbt.NamedTag(player))
    return records


@pytest.mark.parametrize("role", ["injured", "control"])
def test_native_control_job_changes_preserve_health_supplies_and_identity_requirements(role):
    events = village_events()
    for event in events:
        if event["case_id"] in {"after", "chunk_reload"}:
            event["snapshot"]["actors"][role]["variant"] = 7
    assert validate_village_events(events, make_village_plan(), phase="seed")["status"] == "pass"
    events[-1]["snapshot"]["actors"][role]["current"] -= 1
    with pytest.raises(ProbeError, match="health"):
        validate_village_events(events, make_village_plan(), phase="seed")


@pytest.mark.parametrize("variant", [None, nbt.IntTag(7), nbt.ByteTag(7), nbt.IntTag(15)])
def test_saved_control_professions_may_change_but_must_remain_valid_native_data(variant):
    records = _records()
    evidence = validate_village_events(village_events(), make_village_plan(), phase="seed")["observations"]
    key = b"actorprefix" + struct.pack("<Q", ROLES.index("control") + 1)
    named = load_player_nbt(records[key])
    if variant is None:
        named.tag.pop("Variant")
    else:
        named.tag["Variant"] = variant
    records[key] = save_player_nbt(named)
    if variant is None or type(variant) is nbt.IntTag and variant.py_data <= 14:
        worker.verify_saved(records, make_village_plan(), evidence)
    else:
        with pytest.raises(ProbeError, match="natural profession"):
            worker.verify_saved(records, make_village_plan(), evidence)


@pytest.mark.parametrize("role", ROLES)
def test_native_saved_inventory_must_match_last_live_actor_slots(role):
    records = _records()
    evidence = validate_village_events(village_events(), make_village_plan(), phase="seed")["observations"]
    index = ROLES.index(role)
    key = b"actorprefix" + struct.pack("<Q", index + 1)
    named = load_player_nbt(records[key])
    slot = named.tag["ChestItems"][0]
    slot["Name"] = nbt.StringTag("minecraft:carrot")
    slot["Count"] = nbt.ByteTag(9)
    records[key] = save_player_nbt(named)
    with pytest.raises(ProbeError, match="last live observation"):
        worker.verify_saved(records, make_village_plan(), evidence)


@pytest.fixture
def village_run(tmp_path):
    from mcbe_editor.leveldb_writer import LevelDbWriter
    from scripts.engine_checks.runner import WORLD_NAME, sha256, source_hashes, write_json

    world = tmp_path / "server/worlds" / WORLD_NAME
    (world / "db").mkdir(parents=True)
    (world / "level.dat").write_bytes(b"synthetic test world metadata")
    (world / "levelname.txt").write_text("Synthetic natural-village worker test", encoding="utf-8")
    db = LevelDbWriter(str(world / "db"))
    try:
        db.put_batch(_records())
    finally:
        db.close()
    write_json(tmp_path / "village-plan.json", make_village_plan())
    write_json(tmp_path / "catalog.json", {"synthetic_test_catalog": True})
    report = {
        "format": "mcbe-engine-check-v1",
        "suite": "village",
        "run_id": "b" * 32,
        "phases": {"seed": "pass"},
        "editor": source_hashes(),
        "village_plan_sha256": sha256(tmp_path / "village-plan.json"),
        "catalog_sha256": sha256(tmp_path / "catalog.json"),
    }
    write_json(tmp_path / "run.json", report)
    write_json(tmp_path / "seed.village.json", validate_village_events(village_events(), make_village_plan(), phase="seed"))
    return tmp_path, world, report


def test_worker_uses_real_service_and_two_backups_then_requires_every_reload(village_run):
    from mcbe_editor.leveldb_writer import LevelDbWriter
    from scripts.engine_checks.runner import write_json

    directory, world, report = village_run
    edited = worker.run(directory, "edit")
    assert edited["backed_up_saves"] == 2
    assert edited["expected"]["injured"]["current"] == edited["expected"]["injured"]["maximum"] == 40
    assert edited["expected"]["farmer"]["items"] == [{"name": "minecraft:carrot", "count": 4}] + [None] * 7
    with pytest.raises(ProbeError, match="once"):
        worker.run(directory, "edit")
    with pytest.raises(ProbeError, match="reload is required"):
        worker.run(directory, "verify")
    for index, phase in enumerate(("reload1", "reload2"), 1):
        report["phases"][phase] = "pass"
        write_json(directory / "run.json", report)
        write_json(directory / f"{phase}.village.json", validate_village_events(village_events(phase), make_village_plan(), phase=phase))
        db = LevelDbWriter(str(world / "db"))
        try:
            db.put_batch(_records(phase))
        finally:
            db.close()
        assert worker.run(directory, "verify")["verified_reloads"] == index
    with pytest.raises(ProbeError, match="out of order"):
        worker.run(directory, "verify")


@pytest.mark.parametrize("fault", ["village_plan_sha256", "catalog_sha256", "run_id", "suite", "editor"])
def test_worker_rejects_changed_input_binding_before_reading_world(village_run, monkeypatch, fault):
    from scripts.engine_checks.runner import write_json

    directory, _world, report = village_run
    report[fault] = {} if fault == "editor" else "wrong"
    write_json(directory / "run.json", report)
    monkeypatch.setattr(worker, "_read", lambda *_: pytest.fail("Unbound input reached the database"))
    with pytest.raises(ProbeError):
        worker.run(directory, "edit")


@pytest.mark.parametrize(
    "chunk_mode", ["works", "control_jobs", "stays_loaded", "never_returns", "gui_stays_open", "pickup_cancelled", "wrong_pickup_item", "distant_spawn"]
)
def test_reload_script_waits_for_real_events_without_repairing_actors_or_items(chunk_mode):
    from tests.node_runner import run_node

    plan = make_village_plan()
    expected = validate_village_events(village_events("reload1"), plan, phase="reload1")["observations"]["before"]["actors"]
    run_node(
        "const plan="
        + json.dumps(plan)
        + "; const expected="
        + json.dumps(expected, sort_keys=True)
        + "; const chunkMode="
        + json.dumps(chunk_mode)
        + ";\n"
        + r"""
const assert = require('node:assert/strict'), fs=require('node:fs');
const source=fs.readFileSync('scripts/engine_checks/pack/scripts/village.js','utf8').replace(/^import .*;\s*/m,'').replace('export function* ','function* ');
const forbidden=()=>{throw new Error('Reload repaired an actor or inventory');};
let loaded=true, wentAway=false;
const counts={emerald:63,bread:6,carrot:7};
const signals={};
for(const name of ['playerInteractWithEntity','entitySpawn','entityItemPickup']) signals[name]={
 subscribe:cb=>signals[name].callback=cb,unsubscribe:cb=>assert.equal(signals[name].callback,cb)
};
const dimension={id:'overworld',getEntities:()=>loaded?Object.values(actors):[],isChunkLoaded:position=>{
 assert.ok(Object.values(position).every(Number.isInteger),'Chunk API requires block coordinates');
 if(chunkMode==='stays_loaded')return true;
 if(chunkMode==='never_returns' && wentAway)return false;
 return loaded;
},
 spawnEntity:forbidden,runCommand:forbidden,getBlock:p=>({isAir:p.y>=plan.booths.farmer.y,
  typeId:p.y<plan.booths.farmer.y?'minecraft:stone':'minecraft:air'})};
const actors=Object.fromEntries(Object.entries(expected).map(([role,seed])=>[role,{
  id:seed.identity,typeId:seed.type,nameTag:plan.names[role],
  location:{x:plan.booths.farmer.x+0.7,y:plan.booths.farmer.y-0.00001,z:plan.booths.farmer.z+0.3},dimension,
  getComponent(id){
    if(id==='minecraft:health')return {currentValue:seed.current,effectiveMax:seed.maximum,setCurrentValue:forbidden};
    if(id==='minecraft:variant')return {value:seed.variant};
    return {container:{size:8,clearAll:forbidden,setItem:forbidden,getItem:slot=>{
     const item=seed.items[slot];return item?{typeId:item.name,amount:item.count}:undefined;
    }}};
  }
}]));
const player={id:'real-client-double',dimension,location:plan.center,setGameMode:()=>{},
teleport:pos=>{loaded=pos.x<1000;
 if(!loaded)assert.equal(areaActive,false,'Ticking area must be removed before leaving');wentAway ||= !loaded;},sendMessage:()=>{},
getComponent:()=>({container:{size:36,clearAll:forbidden,setItem:forbidden,getItem:slot=>{
 const name=['emerald','bread','carrot'][slot];return name?{typeId:'minecraft:'+name,amount:counts[name]}:undefined;
}}})};
let areaActive=false;
const world={seed:plan.seed,getDimension:()=>dimension,getAllPlayers:()=>[player],
tickingAreaManager:{createTickingArea:()=>({then:resolve=>{areaActive=true;resolve();}}),removeTickingArea:()=>{areaActive=false;}},
afterEvents:{playerInteractWithEntity:signals.playerInteractWithEntity,entitySpawn:signals.entitySpawn},beforeEvents:{entityItemPickup:signals.entityItemPickup}};
const probe=new Function('GameMode','ItemStack','world',source+';return villageRoundtrip;')({Creative:'creative',Survival:'survival'},forbidden,world);
assert.throws(()=>probe({phase:'seed',village_profile:{...plan,seed:'wrong-world'}},()=>{}).next(),/world seed differs/);
const events=[];
const task=probe({phase:'reload1',village_profile:plan,village_expected:expected},(kind,fields)=>{
 events.push({kind,...fields});
 if(fields.stage==='trade_required'){
  if(chunkMode==='control_jobs'){expected.control.variant=7;expected.injured.variant=1;}
  signals.playerInteractWithEntity.callback({player,target:actors.farmer}); counts.emerald=0;counts.bread+=6;
 }
 if(fields.stage==='pickup_required'){
  counts.carrot--;
  if(chunkMode!=='pickup_cancelled')expected.farmer.items[0].count++;
  const item={id:'dropped-carrot',typeId:'minecraft:item',dimension,location:{...player.location,x:player.location.x+(chunkMode==='distant_spawn'?20:1)},
    getComponent:()=>({itemStack:{typeId:'minecraft:carrot',amount:1}})};
  signals.entitySpawn.callback({entity:item});
  signals.entityItemPickup.callback({entity:actors.farmer,item:chunkMode==='wrong_pickup_item'?{...item,id:'different-carrot'}:item});
 }
});
let steps=0,guiTicks=0;
function finish(){while(!task.next().done){
 assert.ok(++steps<1100,'Missing live evidence must not complete');
 if(events.some(event=>event.stage==='trade_required') && counts.emerald===0){
  assert.equal(events.filter(event=>event.case_id==='trade').length,0);
  assert.equal(events.filter(event=>event.stage==='pickup_required').length,0);
  if(++guiTicks===4 && chunkMode!=='gui_stays_open')counts.emerald=62;
 }
}}
if(['gui_stays_open','pickup_cancelled','wrong_pickup_item','distant_spawn'].includes(chunkMode)){
 assert.throws(finish,/Missing live evidence must not complete/);
 assert.equal(events.filter(event=>event.case_id==='pickup').length,0);
}else if(!['works','control_jobs'].includes(chunkMode)){
 assert.throws(finish,chunkMode==='stays_loaded'?/did not unload/:/did not reload/);
 assert.equal(events.filter(event=>event.case_id==='chunk_reload').length,0);
}else{
 finish();
 assert.deepEqual(events.filter(event=>event.kind==='case').map(event=>event.case_id),['before','trade','pickup','after','chunk_reload']);
 assert.equal(events.find(event=>event.case_id==='trade').snapshot.interactions,1);
 assert.equal(events.find(event=>event.case_id==='pickup').snapshot.picked_up,1);
}
"""
    )
