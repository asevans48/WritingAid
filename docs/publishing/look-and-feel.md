# Look and feel

The aim is a calmer app than today's: fewer places to look, one obvious next
step, and nothing on screen that the writer does not need at that moment.
Every point below either replaces something or removes something.

**Fewer places**

1. **Three roles, three places.** The scorecard says *where* the work is, the
   Companion says *what next*, and one Improve window says *how*. Every other
   list of problems is folded into one of these (pieces D.1 to D.4).
2. **One Improve window instead of three.** Suggestions, Rephrase and "Overly
   descriptive?" are separate windows with the same layout: options, an
   editable preview, the changes, a rating. They become one window with the
   kinds of help as tabs (D.2).
3. **One issues list instead of two.** The Style tab and the Companion both list
   problems in the chapter. The list moves into the Companion's queue; the
   Style tab's on and off switches become a small control on the editor (D.3).
4. **A shorter right-click menu.** One "Improve this…" entry opens the Improve
   window. Everything else is grouped (D.1).
5. **Fewer top-level tabs.** Ten today. A proposal to group them into about six
   is made in 0.2 and built in D.4.

**One obvious next step**

6. **A single primary button per screen,** in the app's accent colour. The rest
   is quiet.
7. **A Next fix card** in the Companion: the sentence, what is wrong, a coloured
   before-and-after, Accept. It replaces the list of three fixes and the
   separate overly descriptive section, taking the Companion from seven
   sections to five.
8. **A stage ribbon.** Structure › Scene › Line › Copyedit › Proof. It shows
   where the chapter is and filters what is shown. It is the only new control
   in the plan, and it stands in for a stage picker and a filter menu.
9. **Keys for the queue.** Accept, skip, "not a problem" and move, without the
   mouse. Nothing on screen is added for this.

**Calm and consistent**

10. **One colour per kind of problem, everywhere,** reusing the colours the
    style checks already have.
11. **Shared parts and one palette.** Cards, chips, headers and buttons come from
    one kit, with colours from `src/ui/styles.py`. Newer panels currently set
    their own greys and oranges by hand.
12. **Results arrive as they are ready,** with progress shown in place. No extra
    progress windows.
13. **Empty states that say what to do next,** in one line.
14. **Layouts that respond.** On a narrow screen the side panel is a drawer over
    the text. On a wide screen the text and the Companion sit side by side.

**What makes it pop** is mostly the removal: a heat-map scorecard that reads at
a glance, cells turning green as work is done, and far less around them.

**Left out to avoid clutter:** a progress ring (a plain figure does the job), an
issue strip beside the text and a new pop-out mechanism for side panels (pieces
U.4 and U.5, now cut), a dark theme, a command palette, streaks and
badges.

**Already in the app, and kept:** top-level tabs can be detached into their own
windows and moved to another screen (see
[multi_window_architecture.md](../multi_window_architecture.md)). The scorecard
lives in the Critique tab, so it detaches with it. Grouping tabs (D.4) must
keep every screen detachable. The app has one light theme today; the dark
colours in `src/ui/styles.py` are not used as a theme.
