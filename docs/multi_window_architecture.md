# Multi-Window Mode Architecture

## Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         WindowManager                            │
│                         (Singleton)                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ - Tracks all open windows                                  │ │
│  │ - Manages multi-window mode state                          │ │
│  │ - Coordinates window creation/destruction                  │ │
│  │ - Emits signals for window events                          │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ manages
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐      ┌──────────────┐
│ MainWindow   │    │SecondaryWin 1│  ... │SecondaryWin N│
│   (ID: 0)    │    │   (ID: 1)    │      │  (ID: N)     │
└──────────────┘    └──────────────┘      └──────────────┘
```

## Main Window Structure

```
┌────────────────────────────────────────────────────────────────┐
│                          MainWindow                             │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ MenuBar                                                     │ │
│ │  File | Edit | View (Multi-Window Mode ✓) | Export | Help │ │
│ └────────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ Toolbar                                                     │ │
│ │  [Project Name] | Save | Export | AI                       │ │
│ └────────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │             Horizontal Splitter (3:1)                      │ │
│ │ ┌─────────────────────────────┬──────────────────────────┐ │ │
│ │ │ DetachableTabWidget         │  ChatWidget              │ │ │
│ │ │ ┌─────────────────────────┐ │  ┌──────────────────┐   │ │ │
│ │ │ │ Write | Plot | Chars... │ │  │ AI Assistant     │   │ │ │
│ │ │ └─────────────────────────┘ │  │                  │   │ │ │
│ │ │ ┌─────────────────────────┐ │  │ Message input... │   │ │ │
│ │ │ │  Tab Content Area       │ │  └──────────────────┘   │ │ │
│ │ │ │  (Active widget shown)  │ │                          │ │ │
│ │ │ │                         │ │  Toggle: Ctrl+B          │ │ │
│ │ │ └─────────────────────────┘ │                          │ │ │
│ │ └─────────────────────────────┴──────────────────────────┘ │ │
│ └────────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ StatusBar: "Multi-window mode enabled - Right-click tabs" │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

## Secondary Window Structure

```
┌────────────────────────────────────────────────────────────────┐
│                       SecondaryWindow                           │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ Toolbar: [Project Name] | AI                              │ │
│ └────────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │             Horizontal Splitter (3:1)                      │ │
│ │ ┌─────────────────────────────┬──────────────────────────┐ │ │
│ │ │ DetachableTabWidget         │  ChatWidget              │ │ │
│ │ │ ┌─────────────────────────┐ │  ┌──────────────────┐   │ │ │
│ │ │ │ Characters | World      │ │  │ AI Assistant     │   │ │ │
│ │ │ └─────────────────────────┘ │  └──────────────────┘   │ │ │
│ │ │ ┌─────────────────────────┐ │                          │ │ │
│ │ │ │  Tab Content Area       │ │                          │ │ │
│ │ │ │  (Active widget shown)  │ │                          │ │ │
│ │ │ └─────────────────────────┘ │                          │ │ │
│ │ └─────────────────────────────┴──────────────────────────┘ │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

## DetachableTabWidget Class Hierarchy

```
QTabWidget
    │
    └─── DetachableTabWidget
              │
              ├── Properties:
              │   ├── _is_main_window: bool
              │   ├── _tab_data: Dict[int, Dict]
              │   └── _detachable_tab_bar: DetachableTabBar
              │
              ├── Signals:
              │   ├── tab_detached(int, QPoint)
              │   └── content_changed()
              │
              └── Methods:
                  ├── detach_tab(index) → (widget, label)
                  ├── attach_tab(widget, label, index)
                  ├── merge_tab_to_main_window(index)
                  └── get_all_tab_info() → List[Tuple]
```

## DetachableTabBar (Custom Tab Bar)

```
QTabBar
    │
    └─── DetachableTabBar
              │
              ├── Properties:
              │   ├── _drag_start_pos: QPoint
              │   ├── _drag_initiated: bool
              │   └── _drag_threshold: int (20px)
              │
              ├── Signals:
              │   ├── tab_detach_requested(int, QPoint)
              │   └── tab_close_requested(int)
              │
              ├── Mouse Events:
              │   ├── mousePressEvent() → Start drag tracking
              │   ├── mouseMoveEvent() → Detect drag threshold
              │   └── mouseReleaseEvent() → End drag
              │
              └── Context Menu:
                  ├── "Create New Window"
                  └── "Merge to Main Window"
```

## Data Flow: Tab Detachment

```
1. User Action
   │
   ├─→ Right-click tab → "Create New Window"
   │   └─→ DetachableTabBar._show_context_menu()
   │       └─→ tab_detach_requested.emit(index, pos)
   │
   └─→ Drag tab out of bar
       └─→ DetachableTabBar.mouseMoveEvent()
           └─→ tab_detach_requested.emit(index, pos)

2. Signal Flow
   tab_detach_requested
      │
      └─→ DetachableTabWidget._handle_tab_detach()
          │
          └─→ DetachableTabWidget.tab_detached.emit()
              │
              └─→ MainWindow._handle_tab_detach()

3. Tab Transfer
   MainWindow._handle_tab_detach()
      │
      ├─→ Check multi-window mode enabled
      ├─→ Check not last tab in main window
      ├─→ DetachableTabWidget.detach_tab(index)
      │   └─→ Returns (widget, label)
      │
      └─→ Create SecondaryWindow
          ├─→ SecondaryWindow.__init__()
          ├─→ WindowManager.register_window()
          ├─→ SecondaryWindow.add_tab(widget, label)
          ├─→ position at global_pos
          └─→ show()
```

## Data Flow: Window Closing

```
1. User closes SecondaryWindow
   │
   └─→ SecondaryWindow.closeEvent()
       │
       ├─→ Get all tabs: get_all_tab_info()
       │
       ├─→ For each tab:
       │   ├─→ widget.setParent(None)
       │   └─→ main_window.tab_widget.attach_tab()
       │
       ├─→ WindowManager.unregister_window()
       │
       └─→ event.accept()

2. User disables Multi-Window Mode
   │
   └─→ MainWindow._toggle_multi_window_mode(False)
       │
       ├─→ WindowManager.set_multi_window_mode(False)
       │
       └─→ MainWindow._merge_all_windows()
           │
           └─→ For each SecondaryWindow:
               ├─→ Get all tabs
               ├─→ Move to main window
               └─→ window.close()
```

## Project Data Persistence

```
WriterProject (Pydantic Model)
    │
    └─── window_layout: WindowLayout
              │
              ├── multi_window_mode_enabled: bool
              │
              └── windows: List[Dict]
                     │
                     ├─→ Window Config:
                     │   {
                     │     "tabs": [tab_indices or labels],
                     │     "geometry": {
                     │       "x": int,
                     │       "y": int,
                     │       "width": int,
                     │       "height": int
                     │     },
                     │     "is_main": bool
                     │   }
                     │
                     └─→ Saved on:
                         ├─→ _save_project()
                         │   └─→ _save_window_layout()
                         │
                         └─→ Restored on:
                             └─→ _load_project_into_ui()
                                 └─→ _restore_window_layout()
```

## Signal Flow Diagram

```
                   WindowManager
                        │
        ┌───────────────┼───────────────┐
        │               │               │
   window_created  window_closed  tab_detached
        │               │               │
        ▼               ▼               ▼
   [Register]      [Cleanup]      [Coordinate]
   new window      resources      tab transfer


        DetachableTabWidget
                │
        ┌───────┴────────┐
        │                │
   tab_detached   content_changed
        │                │
        ▼                ▼
   [Create new      [Mark project
    window]          modified]


        MainWindow
            │
    ┌───────┴────────┐
    │                │
project_changed   closeEvent
    │                │
    ▼                ▼
[Save required]  [Cleanup all
                  windows]
```

## State Management

### Multi-Window Mode States

```
┌─────────────────────────────────────────┐
│         SINGLE WINDOW MODE              │
│  (Default - multi_window_mode = False)  │
│                                         │
│  - All tabs in MainWindow               │
│  - Tab reordering allowed               │
│  - No detachment allowed                │
│  - Context menu: (empty)                │
└─────────────────────────────────────────┘
                    │
                    │ View → Multi-Window Mode
                    ▼
┌─────────────────────────────────────────┐
│        MULTI-WINDOW MODE                │
│  (Enabled - multi_window_mode = True)   │
│                                         │
│  - MainWindow + N SecondaryWindows      │
│  - Tab detachment enabled               │
│  - Drag to create windows               │
│  - Context menu:                        │
│    ├─ Create New Window                 │
│    └─ Merge to Main Window              │
└─────────────────────────────────────────┘
                    │
                    │ View → Multi-Window Mode
                    ▼
┌─────────────────────────────────────────┐
│    MERGING BACK TO SINGLE WINDOW        │
│  (Transition)                           │
│                                         │
│  1. Get all secondary windows           │
│  2. For each window:                    │
│     - Extract all tabs                  │
│     - Move to MainWindow                │
│     - Close window                      │
│  3. Set multi_window_mode = False       │
└─────────────────────────────────────────┘
```

## File Structure

```
src/ui/
├── main_window.py              # Main application window
│   ├── MainWindow class
│   │   ├── _toggle_multi_window_mode()
│   │   ├── _handle_tab_detach()
│   │   ├── _merge_all_windows()
│   │   ├── _save_window_layout()
│   │   └── _restore_window_layout()
│   └── Uses: DetachableTabWidget, WindowManager
│
├── secondary_window.py         # Secondary floating windows
│   └── SecondaryWindow class
│       ├── Minimal toolbar
│       ├── DetachableTabWidget
│       ├── ChatWidget
│       └── Auto-merge on close
│
├── detachable_tab_widget.py   # Custom tab widget
│   ├── DetachableTabWidget class
│   │   ├── detach_tab()
│   │   ├── attach_tab()
│   │   └── merge_tab_to_main_window()
│   └── DetachableTabBar class
│       ├── Drag detection
│       └── Context menu
│
└── window_manager.py          # Singleton window manager
    └── WindowManager class
        ├── register_window()
        ├── unregister_window()
        ├── get_all_windows()
        ├── set_multi_window_mode()
        └── close_all_secondary_windows()

src/models/
└── project.py                 # Data models
    └── WindowLayout class
        ├── multi_window_mode_enabled
        └── windows: List[Dict]
```

## Key Design Decisions

### 1. Singleton WindowManager
- **Why**: Ensures single source of truth for window state
- **Benefit**: Easy coordination between all windows

### 2. DetachableTabWidget vs QTabWidget
- **Why**: Need custom drag behavior and context menus
- **Benefit**: Encapsulates all tab management logic

### 3. Auto-merge on Close
- **Why**: Prevents data loss perception
- **Benefit**: User never loses tab content

### 4. Per-project Layouts
- **Why**: Different projects may benefit from different layouts
- **Benefit**: Automatic workspace restoration

### 5. Each Window Has Chat
- **Why**: Makes windows truly independent
- **Benefit**: AI assistance always available

### 6. Main Window Always Exists
- **Why**: Prevents confusion, provides stable reference point
- **Benefit**: Clear hierarchy and merge target

## Performance Considerations

### Memory
- Each SecondaryWindow is a full QMainWindow
- Each window has its own ChatWidget
- Widgets are reused, not recreated when moving

### Signals
- Direct signal connections (no queuing)
- Minimal signal chain depth
- No circular signal dependencies

### Persistence
- Window layout saved as part of project JSON
- Minimal serialization overhead
- Lazy restoration (only on project load)

## Testing Checklist

- [ ] Enable multi-window mode
- [ ] Drag tab out of main window
- [ ] Right-click tab → Create New Window
- [ ] Move tabs between windows
- [ ] Close secondary window (tabs merge)
- [ ] Disable multi-window mode (all merge)
- [ ] Save project with layout
- [ ] Reopen project (layout restored)
- [ ] Close main window (all windows close)
- [ ] Test with last tab in main window
