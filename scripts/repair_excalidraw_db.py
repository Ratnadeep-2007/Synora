import json
import sqlite3
import os

DB_PATHS = ["synesis.db", "backend/synesis.db"]

def repair_db(db_path: str):
    if not os.path.exists(db_path):
        print(f"Skipping {db_path} (does not exist)")
        return

    print(f"Repairing {db_path}...")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT id, project_id, version, elements_json FROM excalidraw_artifacts")
    rows = cur.fetchall()

    updated_count = 0
    for art_id, proj_id, ver, el_json in rows:
        if not el_json:
            continue
        try:
            elements = json.loads(el_json)
        except Exception:
            continue

        changed = False
        el_map = {el["id"]: el for el in elements if isinstance(el, dict) and "id" in el}

        for el in elements:
            if not isinstance(el, dict):
                continue
            
            # Ensure standard critical Excalidraw attributes
            if not el.get("backgroundColor") or not isinstance(el.get("backgroundColor"), str):
                el["backgroundColor"] = "transparent"
                changed = True

            if not el.get("strokeColor") or not isinstance(el.get("strokeColor"), str):
                el["strokeColor"] = "#1e1e1e"
                changed = True

            if not el.get("fillStyle") or not isinstance(el.get("fillStyle"), str):
                el["fillStyle"] = "solid"
                changed = True

            if "strokeWidth" not in el or el["strokeWidth"] is None:
                el["strokeWidth"] = 1
                changed = True

            if not el.get("strokeStyle") or not isinstance(el.get("strokeStyle"), str):
                el["strokeStyle"] = "solid"
                changed = True

            if "roughness" not in el:
                el["roughness"] = 1
                changed = True

            if "opacity" not in el:
                el["opacity"] = 100
                changed = True

            if "angle" not in el:
                el["angle"] = 0
                changed = True

            if "groupIds" not in el or not isinstance(el["groupIds"], list):
                el["groupIds"] = []
                changed = True

            # Text element properties required by Excalidraw canvas renderer
            if el.get("type") == "text":
                text_val = el.get("text") or ""
                if not el.get("originalText"):
                    el["originalText"] = text_val
                    changed = True
                if not el.get("lineHeight"):
                    el["lineHeight"] = 1.25
                    changed = True
                if not el.get("baseline"):
                    el["baseline"] = 14 if (el.get("fontSize") or 16) >= 16 else 10
                    changed = True
                if not el.get("fontSize"):
                    el["fontSize"] = 16
                    changed = True
                if not el.get("fontFamily"):
                    el["fontFamily"] = 1
                    changed = True
                if not el.get("textAlign"):
                    el["textAlign"] = "center"
                    changed = True
                if not el.get("verticalAlign"):
                    el["verticalAlign"] = "middle"
                    changed = True
                if "autoResize" not in el:
                    el["autoResize"] = True
                    changed = True

            # Arrow element coordinates
            if el.get("type") == "arrow":
                src_id = (el.get("startBinding") or {}).get("elementId")
                dst_id = (el.get("endBinding") or {}).get("elementId")
                src_el = el_map.get(src_id)
                dst_el = el_map.get(dst_id)
                if src_el and dst_el and (el.get("x") == 0 and el.get("y") == 0):
                    src_x = float(src_el.get("x", 0))
                    src_y = float(src_el.get("y", 0))
                    src_w = float(src_el.get("width", 220))
                    src_h = float(src_el.get("height", 92))
                    dst_x = float(dst_el.get("x", 0))
                    dst_y = float(dst_el.get("y", 0))
                    dst_w = float(dst_el.get("width", 220))
                    dst_h = float(dst_el.get("height", 92))

                    if dst_x > src_x + 10:
                        start_x = src_x + src_w
                        start_y = src_y + src_h / 2
                        end_x = dst_x
                        end_y = dst_y + dst_h / 2
                    elif dst_x < src_x - 10:
                        start_x = src_x + src_w / 2
                        start_y = src_y + src_h
                        end_x = dst_x + dst_w / 2
                        end_y = dst_y
                    else:
                        start_x = src_x + src_w / 2
                        start_y = src_y + src_h
                        end_x = dst_x + dst_w / 2
                        end_y = dst_y

                    dx = end_x - start_x
                    dy = end_y - start_y
                    el["x"] = start_x
                    el["y"] = start_y
                    el["width"] = max(1.0, abs(dx))
                    el["height"] = max(1.0, abs(dy))
                    el["points"] = [[0, 0], [dx, dy]]
                    changed = True

        if changed:
            cur.execute(
                "UPDATE excalidraw_artifacts SET elements_json = ? WHERE id = ?",
                (json.dumps(elements), art_id),
            )
            updated_count += 1
            print(f"  Updated artifact {art_id} (Project {proj_id} v{ver})")

    conn.commit()
    conn.close()
    print(f"Done {db_path}. Updated {updated_count} artifacts.")

if __name__ == "__main__":
    for p in DB_PATHS:
        repair_db(p)
