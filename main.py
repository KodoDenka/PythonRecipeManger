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

count = 0

def load_keys(file_path):
    return return_json_data(file_path)

def load_tiers(file_path, keys):
    raw = return_json_data(file_path)
    for name, entry in raw.items():
        tiers[name] = TierClass(
            mod_id=entry["mod_id"],
            material=keys[entry["material"]],
            handle=keys[entry["handle"]],
            binder=keys[entry["binder"]],
        )

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

    print("Starting data generation...")
    start_time = time.time()

    clear_old_data()
    start_time = log_and_return_time("Cleared old data", start_time)

    keys = load_keys("common/data/keys.json")
    start_time = log_and_return_time("Loaded keys/ingredients data", start_time)

    load_tiers("common/data/tiers.json", keys)
    start_time = log_and_return_time("Loaded tiers", start_time)

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

