# Polozky horni listy na Waylandu: [id widgetu, klic nastaveni, popisek, vychozi viditelnost].
ITEMS = [
    ["app", "BAR_SHOW_APP", "Application Name", True],
    ["workspaces", "BAR_SHOW_WORKSPACES", "Workspaces", True],
    ["cpu", "BAR_SHOW_CPU", "CPU", False],
    ["tray", "BAR_SHOW_TRAY", "Status Tray Plugin", True],
    ["keyboard", "BAR_SHOW_KEYBOARD", "Keyboard Layouts", True],
    ["network", "BAR_SHOW_NETWORK", "Wi-Fi", True],
    ["sound", "BAR_SHOW_SOUND", "Sound", True],
    ["battery", "BAR_SHOW_BATTERY", "Battery", True],
    ["search", "BAR_SHOW_SEARCH", "Search", True],
    ["control-center", "BAR_SHOW_CONTROL_CENTER", "Control Center", True],
    ["notifications", "BAR_SHOW_NOTIFICATIONS", "Notifications", True]
]

function enabled(conf, item):
    value = conf.get(item[1], "").strip()
    if len(value) >= 2 and (value[0] == "\"" or value[0] == "'"):
        value = value[1:-1]
    end
    if value == "0" or value == "1":
        return value == "1"
    end
    return item[3]
end
