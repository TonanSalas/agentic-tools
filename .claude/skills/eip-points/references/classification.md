 # Classifying a free-text activity into Category + Type

From the user's free-text activity description you must derive an **Activity Category** and **Activity Type**.

## Known Activity Categories

`Account Management`, `Business Development`, `Certification/Recognition`, `Come Together`, `Direct Revenue`, `Education/Coaching`, `Improving Cares`, `Improving Path`, `Industry Contribution/Leadership`, `Industry Participation`, `Merger/Acquisition`, `Networking`, `Operations Support`, `Other`, `Recruiting`, `Sales/Marketing Support`, `User Experience`

The Activity Type list is dependent on the category and only appears after selecting it — **always re-snapshot after selecting the category** to read the real options rather than guessing. Example (Education/Coaching): Adjunct Instructor, Client Brown Bag, ImprovingU Attendance, ImprovingU Course Preparation, ImprovingU Group Discussion, ImprovingU Group Discussion Facilitation, ImprovingU Instructor Delivery, ImprovingU Key Course Attendance, ImprovingU Key Course Instructor Delivery, ImprovingU Key Course Student Work, ImprovingU Planning, ImprovingU Remote Facilitation, Personal Coaching, Project Review Presentation.

If the description doesn't clearly map to one category/type, **default to `Networking` / `Meeting`** and call it out in the preview so the user can correct it before confirming.

## Known Meeting-Type Mappings

Recurring meeting formats should always map to these fixed Category/Type pairs — check the activity description against this list before falling back to a best-guess match:

| Meeting format | Category | Type |
|---|---|---|
| TrustPod | Education/Coaching | ImprovingU Group Discussion |
| AIR MX Remote / AIR for non developers (AIR-branded meetings) | Networking | Meeting |
| Animation Club | Networking | Meeting |
| Daily standups (e.g. "Daily Dragonfly", "Tech team weekly") | — excluded — | not registered as EIP activities (routine, not one-off) |

When a new recurring meeting format comes up, add it here rather than re-guessing it each time.

## Organizer-Based Classification

For informational/social talks that don't match a Known Meeting-Type Mapping above (e.g. Improving Mexico talks like "AFORE", "Diversidad e Inclusión...", "Inteligencia Emocional en el Trabajo"), use the meeting **organizer** as the primary signal before falling back to the generic Networking/Meeting default:

| Organizer | Category | Type |
|---|---|---|
| Armando | Networking | Meeting |
| Sandy | Come Together | (confirm exact Type from live dropdown) |
| Bety | Come Together | (confirm exact Type from live dropdown) |

If the organizer isn't one of the above, fall back to the general default (`Networking` / `Meeting`) per the rule above, and call it out in the preview.
