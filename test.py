from hwgdreqs.gdbrowser import _level_to_data, _parse_level_response, _post_database

LEVEL_ID = "150814334"


def main() -> None:
    normal_level = None
    print(f"1. Searching getGJLevels21.php for level {LEVEL_ID}...")
    try:
        response = _post_database("getGJLevels21.php", {
            "secret": "Wmfd2893gb7",
            "gameVersion": 22,
            "binaryVersion": 51,
            "gdw": 0,
            "type": 0,
            "str": LEVEL_ID,
            "page": 0,
            "total": 0,
            "uncompleted": 0,
            "onlyCompleted": 0,
            "featured": 0,
            "original": 0,
            "twoPlayer": 0,
            "coins": 0,
            "epic": 0,
            "demonFilter": -1,
            "star": 0,
            "noStar": 0,
            "len": -1,
        })
        normal_level = next(
            (level for level in _parse_level_response(response) if level.get("1") == LEVEL_ID),
            None,
        )
        if normal_level:
            print(f"   SUCCESS: {normal_level.get('2')!r} found by normal search; no level string downloaded.")
        else:
            print("   FAILED: normal search returned no matching level.")
    except Exception as error:
        print(f"   FAILED: normal search raised {type(error).__name__}: {error}")

    print(f"2. Downloading metadata through downloadGJLevel22.php for level {LEVEL_ID}...")
    try:
        response = _post_database("downloadGJLevel22.php", {
            "secret": "Wmfd2893gb",
            "gameVersion": 22,
            "binaryVersion": 51,
            "levelID": LEVEL_ID,
        })
        downloaded_level = next(
            (level for level in _parse_level_response(response) if level.get("1") == LEVEL_ID),
            None,
        )
        if not downloaded_level:
            print("   FAILED: download response contained no matching level.")
            return
        data = _level_to_data(downloaded_level, potentially_unlisted=True)
        print(f"   SUCCESS: {data['name']!r} loaded from download response.")
        print(f"   Description decoded: {data['description']!r}")
        print("   The level string was received by this endpoint but was not printed.")
    except Exception as error:
        print(f"   FAILED: level download raised {type(error).__name__}: {error}")

    if normal_level:
        print("3. Summary: normal metadata search succeeded; download was also tested explicitly.")
    else:
        print("3. Summary: normal search failed; download result above is the fallback result.")


if __name__ == "__main__":
    main()
