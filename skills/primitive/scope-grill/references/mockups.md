# Mockups

Read from scope-grill when a round changes what a user sees. The page shows every screen
the round changes, as prototypes the user would take for the app.

1. **Read the screens.** Open the target repo's design tokens and the current code of
   each component the round changes and what sits around it: colors, type scale,
   spacing, shapes, icons, menu order, and copy. Build the crops from those. When the
   repo has no UI yet, use the platform's native controls and say so on the page.
2. **Options side by side.** For each question whose options differ on screen, crop the
   screen to the part the choice changes and show one crop per option, labeled like the
   options, as in `A ✓ In the row` and `B · On the detail screen`. At phone width they
   stack.
3. **Assumed screens.** Below the options, an `Assuming (say if wrong)` section shows
   one crop per screen an assumed default changes, such as a new menu entry, a sheet, or
   a row, captioned with the default. Skip a default an option's crop already shows.
4. **Mark what's new.** Outline each element an option or default adds, such as with a
   dashed line in a color the app doesn't use. Everything else matches what ships today.
5. **Sources.** Name the token and component files the crops come from in one line on
   the page.
