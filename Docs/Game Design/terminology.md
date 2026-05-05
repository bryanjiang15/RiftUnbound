# Terminology

Working glossary for **tftcg**. Entries describe intent; numbers and exact rules may change in design.

---

## Core entities


| Term         | Definition                                                                                                                                                                                                                                                                                                                                                                          |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Champion** | The player’s main combat character. Each run, the player picks one champion and may **buy/select up to two** additional champions. Having more champions unlock color synergy providing bonuses, but having less champions buff the champion and unlock more abilities. Champions participate in the **combat** phase.                                                              |
| **Ghost**    | The opponent faced each **combat** phase. Ghosts use boards aligned with **player progression** in the match; they may be **historical player snapshots** (exact sourcing TBD). Before fighting a given ghost, the player can **scout** a board state from an **earlier round** than that ghost’s fight (which round and how lag is bounded—see [Open questions](#open-questions)). |


---

## Cards and phases


| Term                        | Definition                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Cards**                   | Played primarily in **planning**, in line with typical TCG sequencing unless a card says otherwise.                                                                                                                                                                                                                                                                                                                             |
| **Colors**                  | Similar to the color system in MTG, defining the playstyle of the champion and cards.                                                                                                                                                                                                                                                                                                                                           |
| **Spells**                  | Cards whose effects resolve in **planning** (baseline model).                                                                                                                                                                                                                                                                                                                                                                   |
| **Equipment / enchantment** | Persistent modifiers similar in role to *Magic* artifacts: attach to a **champion** or **allies** to improve them. Naming (“equipment” vs “enchantment”) may unify later.                                                                                                                                                                                                                                                       |
| **Ally**                    | Supporting characters represented as **cards**. Played during **planning**, with their own **health** and **lives**. Positioned on **the board** for **combat**. Each combat, when they lose all their health, they are gone from the combat and lose one life. If they are alive, they keep the life and also keep their current health. When they lose all health, they are removed from the board into the graveyard/discard |


### Deferred card categories

**Traps**, **field / location**, and similar types exist in the broader design space but are **out of scope** until core combat and planning loops are stable.

---

## Board and combat


| Term          | Definition                                                                                                                                                                                                                      |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The board** | A **hex-grid** layout (TFT-style) where champions and allies are placed for combat.                                                                                                                                             |
| **Combat**    | Turn-based flow comparable to **Hearthstone Battlegrounds**, combined with **TFT-like** positioning: units **pathfind**, **attack**, and **use abilities** when rules allow. Exact initiative and timing are design-detail TBD. |


---

## Resources


| Term         | Definition                                                                                                                                               |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Resource** | **Not finalized.** Draft direction: a **mana-style** pool similar to **Hearthstone** for paying card costs during planning (and possibly elsewhere—TBD). |


---

## Open questions

Items called out here are **not yet locked** in this doc; resolve them in design or rules docs when ready.


| Topic                   | What’s unclear                                                                                           |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| **Resource model**      | Mana-like draft vs alternatives; refresh curve, max crystals, cross-phase use.                           |
| **Ghost sourcing**      | How **past players** are chosen; fairness and pool constraints.                                          |
| **Progression match**   | What “**same progression**” means for ghost boards (mirror round, ELO band, snapshot timing).            |
| **Scouting**            | Precisely **which prior round’s** ghost board is visible and whether scouting is optional or guaranteed. |
| **Deferred card types** | Behavior and timing for **traps**, **fields/locations** when they enter scope.                           |
| **Equipment taxonomy**  | Single card type vs split **equipment** vs **aura/enchantment** rules.                                   |


