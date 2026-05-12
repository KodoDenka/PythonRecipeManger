import json
import os
import shutil
import time
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class TierClass:
    mod_id: str
    material: list[str]
    handle: list[str]
    binder: list[str]

tiers: dict[str, TierClass] = {}
keys = {}

def create_key(prefix, namespace, identifier):
    keys[identifier] = [prefix, f"{namespace}:{identifier}"]


def create_key_data():
    # Minecraft and Common
    create_key("tag", "c", "wood_sticks")
    create_key("item", "minecraft", "iron_nugget")
    create_key("item", "minecraft", "blaze_rod")
    create_key("item", "minecraft", "blaze_powder")

    # Twilight Forest
    for item in ["fiery_ingot", "knightmetal_ingot", "ironwood_ingot", "steeleaf_ingot"]:
        create_key("item", "twilight_forest", item)

    # Deeper Darker
    create_key("item", "deeperdarker", "reinforced_echo_shard")

    # Souls Weapons
    create_key("item", "soulsweapons", "lost_soul")

    # Better End
    #TODO add

    # Better Nether
    #TODO add

    # Blue Skies
    for item in [
        "pyrope_gem", "aquite", "diopside_gem", "charoite", "horizonite_ingot",
        "turquoise_cobblestone", "lunar_cobblestone", "bluebright_planks",
        "lunar_planks", "starlit_planks", "dusk_planks", "frostbright_planks",
        "maple_planks", "comet_planks"
    ]:
        create_key("item", "blue_skies", item)

    # Undergarden
    for item in ["cloggrum_ingot", "froststeel_ingot", "utheric_shard", "forgotten_ingot"]:
        create_key("item", "undergarden", item)

def create_tier_data():

    # Twilight Forest
    create_tier("knightmetal", "twilight_forest", keys["knightmetal_ingot"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("fiery", "twilight_forest", keys["fiery_ingot"], keys["blaze_rod"], keys["blaze_powder"])
    create_tier("ironwood", "twilight_forest", keys["ironwood_ingot"], keys["wood_sticks"], keys["iron_nugget"])   
    create_tier("steeleaf", "twilight_forest", keys["steeleaf_ingot"], keys["wood_sticks"], keys["iron_nugget"])

    # Blue Skies
    create_tier("pyrope", "blue_skies", keys["pyrope_gem"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("aquite", "blue_skies", keys["aquite"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("diopside", "blue_skies", keys["diopside_gem"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("charoite", "blue_skies", keys["charoite"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("horizonite", "blue_skies", keys["horizonite_ingot"], keys["wood_sticks"], keys["iron_nugget"])

    create_tier("turquoise_stone", "blue_skies", keys["turquoise_cobblestone"], keys["wood_sticks"], keys["turquoise_cobblestone"])
    create_tier("lunar_stone", "blue_skies", keys["lunar_cobblestone"], keys["wood_sticks"], keys["lunar_cobblestone"])

    create_tier("bluebright_wood", "blue_skies", keys["bluebright_planks"], keys["wood_sticks"], keys["bluebright_planks"])
    create_tier("lunar_wood", "blue_skies", keys["lunar_planks"], keys["wood_sticks"], keys["lunar_planks"])
    create_tier("starlit_wood", "blue_skies", keys["starlit_planks"], keys["wood_sticks"], keys["starlit_planks"])
    create_tier("dusk_wood", "blue_skies", keys["dusk_planks"], keys["wood_sticks"], keys["dusk_planks"])
    create_tier("frostbright_wood", "blue_skies", keys["frostbright_planks"], keys["wood_sticks"], keys["frostbright_planks"])
    create_tier("maple_wood", "blue_skies", keys["maple_planks"], keys["wood_sticks"], keys["maple_planks"])
    create_tier("comet_wood", "blue_skies", keys["comet_planks"], keys["wood_sticks"], keys["comet_planks"])

    # Undergarden
    create_tier("cloggrum", "undergarden", keys["cloggrum_ingot"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("froststeel", "undergarden", keys["froststeel_ingot"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("utheric", "undergarden", keys["utheric_shard"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("forgotten", "undergarden", keys["forgotten_ingot"], keys["wood_sticks"], keys["iron_nugget"])

def return_json_data(file_path):

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"JSON file not found at {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in file: {file_path}\nError: {e}")
    except Exception as e:
        raise RuntimeError(f"An error occurred while reading the file: {e}")



def create_recipe_data(loader):
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:
            create_shaped_recipe(
                sword=sword,
                name=tier_name,
                mod_id=tier.mod_id,
                material=tier.material,
                handle=tier.handle,
                binder=tier.binder,
                loader=loader,
            )

def create_tier(name, mod_id, material, handle, binder):
    tiers[name] = TierClass(mod_id, material, handle, binder)

    #for sword in SWORD_SETS:
    #    create_shaped_recipe(sword, name, mod_id, material, handle, binder)

def get_loader_conditions(mod_id, loader):
    if loader == "fabric":
        return "fabric:load_conditions", [{"condition": "fabric:all_mods_loaded", "values": [mod_id]}]
    elif loader == "forge":
        return "conditions", [{"type": "forge:mod_loaded", "modid": mod_id}]
    print("Loader not recognized or supported.")
    return None, []

def get_result_item(mod_id, name, sword):
    if mod_id == "blue_skies":
        return f"blue_skies:{name}/{sword}"
    return f"knavesneeds:{mod_id}/{name}/{sword}"

def write_json(path: str, data: dict) -> None:
    global count
    count = count + 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def create_shaped_recipe(sword, name, mod_id, material, handle, binder, loader):
    pattern = SWORD_PATTERNS.get(sword, [])
    result = get_result_item(mod_id, name, sword)
    condition_type, conditions = get_loader_conditions(mod_id, loader)

    recipe_keys = {
        "H": {str(handle[0]): str(handle[1])},
        "M": {str(material[0]): str(material[1])}
    }

    if any("B" in row for row in pattern):
        recipe_keys["B"] = {str(binder[0]): str(binder[1])}

    json_data = {
        condition_type: conditions,
        "type": "minecraft:crafting_shaped",
        "category": "equipment",
        "key": recipe_keys,
        "pattern": pattern,
        "result": {"item": result}
    }

    namespace = "blues_skies" if mod_id == "blue_skies" else "knavesneeds"
    filename = f"{loader}/data/{namespace}/recipes/{mod_id}/{name}/{sword}.json"

    write_json(filename, json_data)

def create_model_date():
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:

            namespace = "blues_skies" if tier.mod_id == "blue_skies" else "knavesneeds"

            json_data = {
                "parent" : f"knavesneeds:items/templates/{sword}",
                "textures" : {
                    "layer0" : f"knavesneeds:items/{tier.mod_id}/{tier_name}/{sword}"
                }
            }


            filename = f"fabric/assets/{namespace}/models/item/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)
            filename = f"forge/assets/{namespace}/models/item/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)


def create_weapon_attributes_date():
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:

            json_data = {
                "parent": f"knavesneeds:{sword}"
            }

            namespace = "blues_skies" if tier.mod_id == "blue_skies" else "knavesneeds"
            filename = f"fabric/data/{namespace}/weapon_attributes/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)
            filename = f"forge/data/{namespace}/weapon_attributes/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)

def create_unlock_data():
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:
            result = get_result_item(tier.mod_id, tier_name, sword)
            json_data = {
                "parent": "minecraft:recipes/root",
                "criteria": {
                    "has_material": {
                        "conditions": {
                            "items": [
                                {
                                    "items": tier.material
                                }
                            ]
                        },
                        "trigger": "minecraft:inventory_changed"
                    },
                    "has_the_recipe": {
                        "conditions": {
                            "recipe": result
                        },
                        "trigger": "minecraft:recipe_unlocked"
                    }
                },
                "requirements": [
                    [
                        "has_material",
                        "has_the_recipe"
                    ]
                ],
                "rewards": {
                    "recipes": [
                        result
                    ]
                },
                "sends_telemetry_event": False
            }

            namespace = "blues_skies" if tier.mod_id == "blue_skies" else "knavesneeds"
            filename = f"fabric/data/{namespace}/advancements/recipes/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)

#Credit to https://stackoverflow.com/questions/185936/how-to-delete-the-contents-of-a-folder
def clear_old_data():
    for folder in ["fabric", "forge"]:
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print('Failed to delete %s. Reason: %s' % (file_path, e))



def log_and_return_time(message, start_time):
    elapsed = (time.time() - start_time) * 1000
    print(f"{message} (took {elapsed:.2f}ms)")
    return time.time()

if __name__ == '__main__':
    global SWORD_PATTERNS
    global count

    print("Starting data generation...")
    start_time = time.time()

    clear_old_data()
    start_time = log_and_return_time("Cleared old data", start_time)

    create_key_data()
    start_time = log_and_return_time("Created keys/ingredients data", start_time)

    create_tier_data()
    start_time = log_and_return_time("Created tiers", start_time)

    SWORD_PATTERNS = return_json_data("common/patterns/sword_patterns.json")
    start_time = log_and_return_time("Loaded sword patterns", start_time)

    create_recipe_data("fabric")
    start_time = log_and_return_time("Made recipes for Fabric", start_time)

    create_recipe_data("forge")
    start_time = log_and_return_time("Made recipes for Forge", start_time)

    create_model_date()
    start_time = log_and_return_time("Created model data", start_time)

    create_weapon_attributes_date()
    start_time = log_and_return_time("Created weapon attributes data", start_time)

    create_unlock_data()
    start_time = log_and_return_time("Created unlock data", start_time)

    print(f"Finished! Created {count} files.")

