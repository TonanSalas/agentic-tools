 # Classifying a free-text activity into Category + Type

From the user's free-text activity description you must derive an **Activity Category** and **Activity Type**.

## Known Activity Categories and Types

The Activity Type list is dependent on the category and only appears after selecting it — **always re-snapshot after selecting the category** to read the real options rather than guessing, since this list can change over time. Snapshot taken 2026-09-10:

| Category | Activity Types |
|---|---|
| Account Management | Azure Partner Admin Link, Consulting Contract <=$10K, Consulting Contract >$100K, Consulting Contract >$10K and <=$100K, Consulting/Training/Placement Lead - Prospect, Participation in Bluesheet Creation, Placement Contract, Qualified Consulting Lead, Qualified Contact, Training Contract |
| Business Development | Consulting - Prospect, Consulting Contract <=$10K, Consulting Contract >$100K, Consulting Contract >$10K and <=$100K, Placement Contract, Placement Prospect, Qualified Consulting lead, Qualified Contact, Qualified Placement Lead, Training Contract, Training Prospect |
| Certification/Recognition | Microsoft Certification, Microsoft MVP, Other Certification, Scrum.org (PST, Trainer) |
| Come Together | Challenge Participation, In-Person Attendance, Virtual Attendance |
| Direct Revenue | 40 Billable Hour Week, OVER 40 Billable Hour Week, Required Support - 8pm-6am, Required Support - Weekend |
| Education/Coaching | Adjunct Instructor, Client Brown Bag, ImprovingU Attendance, ImprovingU Course Preparation, ImprovingU Group Discussion, ImprovingU Group Discussion Facilitation, ImprovingU Instructor Delivery, ImprovingU Key Course Attendance, ImprovingU Key Course Instructor Delivery, ImprovingU Key Course Student Work, ImprovingU Planning, ImprovingU Remote Facilitation, Personal Coaching, Project Review Presentation |

### ImprovingU class Quantity

For `ImprovingU Attendance`, `ImprovingU Instructor Delivery`, and their `Key Course` variants, **Quantity is per session, not per hour** — despite the field's "class hour" label and description text ("record each full hour..."), always use `1` for a single class session. Confirmed 2026-09-10 while registering 3 instructor-delivery sessions: an auto-generated invite link had prefilled Quantity 2 (from session duration), but the correct value the user confirmed was 1.

### ImprovingU Key Course vs. regular class

There's no dropdown field distinguishing "Key Course" from a regular ImprovingU class — it's a judgment call based on whether the course is one of Improving's designated flagship/key curriculum. Confirmed 2026-09-10: "AI Spec-Driven Development" and "Core AI Skills" ARE Key Courses (use the `Key Course` type variants), even though an `eip-points-invite`-generated attendee link for those same sessions defaulted to the plain (non-Key) `ImprovingU Attendance` type — don't trust that link's type as the source of truth for Key Course status, ask the user if unsure.
| Improving Cares | Community Service |
| Improving Path | Active Commitment, Meeting, Professional Development Coaching |
| Industry Contribution/Leadership | Board Participation, Lead User Group, Open Source or Internal Development, Presentation - Conference, Presentation - Improving Talks, Presentation - Lightning Talk, Presentation - Major, Presentation - User Group, Publication - Major, Publication - Minor |
| Industry Participation | Conference - Business Day, Conference - Vacation Day, Conference - Weekend, Podcast Contribution, Podcast Production, Relevant Blog Post, Relevant Social Media Posts, User/Professional Group Attendance |
| Merger/Acquisition | Letter of Intent/Terms Sheet, Letter of Interest, Qualified Lead |
| Networking | Improving Event Attendance, Improving Event Host, Improving Event Planning, Meeting, Partner Event |
| Operations Support | Corporate Initiative Meeting, Lead Corporate Initiative, Maintain Business Report, Maintain KPI Report, Website Development, Weekend Support |
| Other | Miscellaneous |
| Recruiting | Interview - In Person, Interview - Phone, Referral - Hire, Referral - NonHire |
| Sales/Marketing Support | Case Study Creation - Interviewee, Case Study Creation - Interviewer, Create News Item, Create Produced Collateral, Create Webpage Content, Email Campaign, Proposal - Large, Proposal - Small, Support Proposal (estimation), Support Sales Meeting, User Group Host, User Group Referral - Large (20+ people), User Group Referral - Other |
| User Experience | *(no Activity Types configured — dropdown stays empty after selecting this category)* |

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
| Sandy | Come Together | Virtual Attendance (confirmed 2026-09-10 — Sandy's series are Teams-virtual talks) |
| Bety | Come Together | (confirm exact Type from live dropdown) |

If the organizer isn't one of the above, fall back to the general default (`Networking` / `Meeting`) per the rule above, and call it out in the preview.
