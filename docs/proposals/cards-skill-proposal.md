# A tiered card system for solo-with-agents delivery

Quick note on how this was built: I ran the methodology and prior-art research, then had a separate design agent draft its own version of the card system independently, and triangulated the two. Where both drafts landed in the same place I've treated that as high confidence. Where they diverged, I've called it out and made a recommendation. The divergences were mostly about how lean to go, which is the right thing to be arguing about here.

## Part 1: What the research says

### Agile, Scrum, and Kanban for a solo operator

The consensus across the practitioner literature is blunt and consistent: Scrum does not survive contact with a team of one. A team is, definitionally, two or more people, and Scrum's machinery assumes that. The Daily Scrum, sprint planning as a negotiation, the retro as a meeting, the Product Owner and Scrum Master roles, self-organization, team velocity, all of it loses meaning when the "team" is one person plus their tools. The harsher takes put it well: a solo person running Scrum is usually "just creating a to-do list," and there's a whole "Scrum Solo considered harmful" thread arguing the ceremony adds cost without the collaboration benefit it was designed to buy. Scrum for one is a to-do list wearing a lanyard.

What does transfer from the agile world is smaller and more useful. The backlog as a single prioritized list of work survives. The "definition of done" survives, and in this system it becomes the acceptance criteria on each card. Iterative reprioritization survives. The user story as the unit of input survives, and it becomes the literal input to the skill. And story points are worth noting specifically: agile story points already blend complexity, risk, and repetition into one number, which is a direct ancestor of the dual-axis point value you're describing. The idea of a single integer that compresses more than one dimension is not new. Wiring that integer to a model tier is the part that's new.

Kanban, and Personal Kanban specifically, is the piece that actually fits a solo operator. Visualize the work, limit work in progress, manage flow, improve continuously. The standard Personal Kanban board (Backlog, Doing, Done, with a small WIP limit) maps almost exactly onto the card lifecycle you want.

There is one genuinely interesting twist, and it's the kind of "far out but grounded" observation worth building on. Personal Kanban's WIP limit exists because a human can only hold one to three things in focus at once. Your system's entire premise is that the worker is a swarm of parallel agents, so the human attention limit dissolves. But the limit does not disappear, it relocates. Your real WIP ceiling becomes two things: how many genuinely independent cards your planning step can produce, and how many cards you can actually afford to run and review. So the system keeps Kanban's board and flow, keeps "limit WIP" as a real concept, and just moves the constraint from your attention to your planner's decomposition quality and your runner's capacity. That relocation is worth making explicit in the design, and it is below.

### Prior art on agent task decomposition and model routing

There is a lot of recent work here, and it splits into two mature halves that nobody has cleanly joined.

On the decomposition side, the pattern of "markdown task files in a folder that agents claim and complete" already exists in the wild. TASKS.md is a lightweight markdown task-queue spec where agents read the file, claim a task by tagging it, implement it, and delete it when done. Taskmd is a similar local-first markdown task system built so any coding agent can read and write tasks without custom integrations. On the "turn a user story into agent work" side, Agent Stories adapts the agile user-story format into small verifiable units matched to agent capabilities, and GitHub's Spec Kit turns a spec into checklists and task breakdowns for coding agents. Practitioner guidance on decomposition converges on a clean rule: tasks should be small enough to understand completely, large enough to deliver value, and independent enough to avoid blocking.

On the AI-agent kanban side, there is now a small crowd of tools. Vibe Kanban orchestrates Claude Code, Codex, and others in parallel, auto-creating git worktrees and moving cards as agents start and open PRs. Kangentic, Claw-Kanban, Cline Kanban, and agent-kanban are all variations on the theme of a task board built to drive agents rather than humans. Claw-Kanban even does role-based auto-assignment. But across all of them, the tier or agent selection is manual or role-based. None of them derive the tier from the task itself.

On the routing side, the academic and commercial work is solid: RouteLLM trains routers that cut cost up to 85 percent while keeping most of the quality, FrugalGPT cascades from cheap models up to expensive ones only when the cheap answer looks unreliable, Microsoft's BEST-Route picks both model and sample count by query difficulty, and commercial routers like OpenRouter's Auto Router, NotDiamond, Martian, and Requesty do real-time cost-versus-quality routing. The closest thing to your idea is "Triage," which routes software tasks to model tiers using code-quality signals, and IBM's argument that frontier models are overkill for roughly 80 percent of coding tasks. But all of these route at the granularity of a single API call, invisibly, and they mostly route on difficulty with cost as a budget constraint. They do not expose a per-task knob, and they do not treat "how much accuracy matters here" as a separate dial from "how hard is this."

The execution substrate is also well established. The standard answer for running many agents in parallel without them stepping on each other is git worktrees, one per agent, and tools like Claude Squad and ccswarm already do this. Worth knowing: opencode has an open feature request for dynamic model selection for subagents spawned via the task tool. That confirms your model-pinning constraint is not a quirk of your setup, it is a real and currently unsolved limitation across the tooling.

So here is what's genuinely novel in what you're proposing, and it's worth being clear about because it tells you where to spend design effort. The novel part is the dual-axis point value made explicit and human-facing: difficulty and stakes as separate dials, collapsed into one small integer that lives on a todo card and deterministically picks a model. Routers treat quality as a global target, not a per-task setting. Agent kanban boards have the board but not the task-derived tier. You're proposing to join the two halves. The pitfall the research is loudest about is exactly the thing your refinement already anticipates: difficulty and stakes genuinely diverge (a one-line change to billing code is trivial but high-stakes), so a single blended scalar can mis-route unless you keep the axes visible underneath it.

## Part 2: Reading of your proposed system

The bones are good and I'd keep almost all of it. A `_dev`-level sibling folder for project-agnostic todos is the right call. Cards as the unit, point value mapped to model tier, project location recorded on the card, multi-agent planning into single-agent execution, all sound. The independent design draft and I converged on every one of those without prompting, which is a good sign.

The things that need refining, and that the refinements you sent address, are: the point value is not a single difficulty ladder and the format has to show that, the delivery should be a skill rather than a loose convention, and the planning-versus-execution split needs to be a real architectural seam, not just a description of mood. The rest of this is the proposal with those folded in.

## Part 3: The proposal

### The delivery mechanism: a `/cards` skill

The system is delivered as one skill, invoked as `/cards [user story or pasted discussion]`. Because it is project-agnostic and used from anywhere under `C:\dev`, it should be installed globally rather than living inside any one project. Package it as a plugin if your setup supports that, or place the skill folder wherever your global skills live (a `_meta\skills\` location would fit your convention). The skill folder itself holds three things: the planning workflow and sizing rubric (the SKILL.md), the card template, and a short spec file that documents the field definitions and the tier table in one place.

Invocation does five things in order. First, resolve context: read the relevant root convention files (NAMING_CONVENTIONS.md for the ID format, SESSION_PROTOCOL.md for any execution protocol the cards should respect) and confirm the target project path. Second, run the planning step (below). Third, assign point values from the two axes (below). Fourth, emit a dry-run summary: card count, point-value histogram, dependency edges, and the count of immediately-claimable cards. Fifth, on your approval, write the card files and a batch manifest.

The planning step is the part that gets real investment, because the research is clear that decomposition quality is the whole ballgame. The default is two agents, which matches your "an agent, or two agents" instinct and keeps it lean: a Planner that decomposes the story into the smallest independent units and assigns the two axes, and an adversarial Reviewer whose only job is to find hidden coupling, missing setup steps, ambiguous acceptance criteria, and ordering hazards. For large or genuinely ambiguous stories, scale to three by splitting the Planner into a Decomposer and an Estimator. Disagreements between planning agents get logged in the batch manifest rather than silently averaged, because a disagreement about whether two cards are independent is a signal you want to see, not smooth over. These planning agents are directly invoked and model-pinned to a high tier. Planning is the one place you spend opus freely.

The guardrails: any card the Reviewer flags as not independently runnable gets split or merged before anything is written. Any card estimated at more than roughly one agent-session of work gets sent back to be decomposed further. The gate is per-card size, not batch size. One hundred-plus cards is fine. One card that's secretly an epic is not.

### Folder layout

The card folder is `C:\dev\_cards\`, a hidden meta sibling that matches your existing `_meta`, `_scripts`, `_templates`, `_archive` convention so it reads as native rather than bolted on.

```
C:\dev\_cards\
  README.md          spec: field definitions, the tier table, lifecycle rules
  backlog\           cards ready to be claimed
  active\            claimed, one agent working each
  done\              completed, kept until swept
  blocked\           failed or waiting on a dependency or a human
  _batches\          one manifest per /cards run, for provenance
  _templates\        the card template (or defer to C:\dev\_templates\)
```

### The dual-axis point model

This is the core refinement, so it gets its own treatment. The six tiers are 1 haiku, 2 haiku with extended thinking, 3 sonnet, 4 sonnet with extended thinking, 5 opus, 6 opus with extended thinking. Your two orderings (difficulty as 1, 2, 3, 5, 4, 6 and accuracy-importance as 1, 2, 3, 4, 5, 6) are not two views of one scale, they are two real axes, and they decompose cleanly:

- The model **family** (haiku, sonnet, opus) tracks **stakes**, how much accuracy matters. This is why the accuracy ordering is a straight ladder: family increments dominate it.
- **Extended thinking** tracks **difficulty**, the length and branchiness of the reasoning chain. This is why the difficulty ordering interleaves: extended thinking moves difficulty-handling enough that sonnet with extended thinking (4) out-handles plain opus (5) on a long multi-step task, even though plain opus out-ranks it on raw per-step accuracy.

That gives a clean three-by-two grid, and the point value is just the label of the cell:

```
                     DIFFICULTY
                  shallow      deep
  STAKES  low      1 haiku      2 haiku+ET
   (fam)  med      3 sonnet     4 sonnet+ET
          high     5 opus       6 opus+ET
```

The planner assigns a card by answering two questions, and the rubric in README.md states them plainly. Question one, stakes: if this card's output is wrong or sloppy, how expensive is that and how hard is it to catch? Cheap and obvious is low, real rework is medium, expensive or hard to detect or load-bearing (security, billing, data migrations, public API, anything irreversible) is high. Question two, difficulty: is the reasoning chain a few clear steps, or many branching ones? The default posture is to pick the smallest cell that clears both bars, because the point value is supposed to encode the most efficient fit, not the most impressive one. You escalate with a reason, you do not escalate by default.

One important consequence for the constraint section below: stakes is the hard part of the assignment and difficulty is the soft part. Getting the family wrong on a high-stakes card means a wrong answer ships. Getting extended thinking wrong means the card is slower or needs a retry. So stakes sets a model-family **floor**, and difficulty only tunes extended thinking. That asymmetry is what makes the advisory execution path tolerable.

### Card file format and fields

Cards are markdown with YAML frontmatter. Markdown because it is git-diffable, human-skimmable, and an executing agent reads the body as a plain brief with no parser required. It also matches the `.md` convention already running through your `C:\dev` root.

Naming defers to NAMING_CONVENTIONS.md for the project prefix and ID scheme rather than hardcoding one. A reasonable shape is `PREFIX-seq-slug.md`, for example `NEXUS-0042-add-rate-limit.md`.

The frontmatter fields, each of which earns its place:

- `id` stable unique identifier
- `title` short imperative line
- `project` absolute path, for example `C:\dev\project-nexus`. This is the required project-location field, and it is absolute because the executing agent is amnesiac and has nothing else to anchor on
- `points` the 1 to 6 value, the required point field, kept mainly for fast human scanning
- `model` and `extended_thinking` the operative execution fields, derived from the cell
- `stakes` and `difficulty` the two axis reads, stored separately so the assignment is auditable and so old cards can be re-mapped if the tier table changes
- `model_floor` the family floor set by stakes, the hard constraint the advisory path must respect
- `pin_required` true when stakes is high, meaning this card may only run on the honorable execution path
- `sizing_note` one line naming both axis reads and why this cell
- `depends_on` list of card IDs that are hard prerequisites only, ideally empty
- `touches` files or globs the card expects to modify, used for conflict detection
- `batch` the `/cards` run that created it, linking back to the manifest
- `created` date
- `claimed_by` agent or session ID, null until claimed
- `model_used` what actually ran, filled in by the executor, which is how the assigned-versus-actual gap becomes visible instead of hidden

The body is the self-contained brief, and this is non-negotiable because the executing agent has no memory of planning. It has five short sections: **Context** (why this card exists, two to four sentences), **Scope** (what to do, concrete), **Out of scope** (explicit, this is what stops two parallel cards from fighting over intent), **Acceptance criteria** (the checklist the agent self-verifies against, your "definition of done" reborn), and **Pointers** (the files, the relevant fragment of the user story, anything the amnesiac needs).

### Card lifecycle

State is the folder the card is in. Backlog, active, done, blocked. There is a real design choice here and I'll put it in the options section, but the recommendation is folder-as-truth with no separate status field, because a redundant status field is a thing that can drift, and the leanest correct design has nothing to drift.

A card flows backlog to active to done. An agent claims a card by **atomically moving** the file from `backlog\` to `active\`, then writes `claimed_by`. The move is the lock. On a single machine and a single volume, a rename either succeeds or fails cleanly, so the first agent to move a card wins and any other agent that tries gets a "not found" and simply grabs the next card. No lock files, no registry, no coordination service. This is the leanest collision-safe primitive available and it scales fine to a hundred-plus pollers. When a card passes its acceptance criteria and its work is committed, the executor moves it to `done\`. A card that fails or hits a wall moves to `blocked\` with a short block reason appended to the body.

Dependencies and parallelism are managed through one rule: `depends_on` lists hard prerequisites only, and a card is claimable only when every ID in its `depends_on` is in `done\`. The planner is pushed hard to minimize these edges, because the dependency graph you want is wide and shallow. File overlap is resolved at planning time, not execution time: if two cards both `touches` the same file, the planner either makes one depend on the other or merges them. You do not let git conflicts be your scheduler. The dry-run's count of immediately-claimable cards is your decomposition quality metric. If that number is low, the breakdown is too coupled and it goes back.

Done cards are swept on a cadence into your existing `C:\dev\_archive\` so `done\` stays scannable. Each card creation and each folder move is a small git commit, which means `git log` is the audit trail for free, which is exactly the lightweight traceable process you already value.

### Execution: parallelism and the model-pinning constraint

Execution is one fresh agent per card. It reads the card, works in `project` (ideally in its own git worktree, which is the established pattern for parallel agents and pairs naturally with the `touches` field), self-checks against the acceptance criteria, commits, and moves the card.

Now the constraint you asked me to address head-on. A directly-invoked sub-agent can have its model pinned. A spawned background task sometimes cannot. So the card-to-model mapping is fully honorable on one path and only advisory on the other. The design handles this by making stakes decide not just the model but which execution path a card is even allowed to use:

- **Honorable path** (directly-invoked sub-agent): model is pinned to the card's assignment, the mapping is fully honored. Every `pin_required` card, meaning every high-stakes card, points 5 and 6, must run here. The runner refuses to hand a `pin_required` card to background execution. If no honorable slot is free, the card waits. A high-stakes card waiting is fine. A high-stakes card silently running on haiku is not.
- **Advisory path** (spawned background task): the model may not be pinnable. The card still carries its full assignment, and the executor records what actually ran in `model_used`. Points 1 through 4 are allowed here, because the asymmetry from the dual-axis model means a wrong model on a low-or-medium-stakes card is an efficiency loss, not a correctness failure. Worst case you overspent on a trivial card or under-thought a medium one, and the acceptance criteria are there to catch the latter.

The gap is made visible rather than wished away. Because every executor writes `model_used`, a trivial script in your existing `_scripts\` can sweep `done\`, diff `model` against `model_used`, and report mismatches. That diff, plus the claimable-card-count from planning, is your automated stand-in for the agile retro: it is the feedback loop that tells you whether the planner is sizing well and whether the tier table is still accurate. Continuous improvement, Kanban-style, without a meeting.

On the relocated WIP limit from Part 1: the runner should carry two explicit, tunable caps, `max_parallel` overall and a separate `max_parallel_pinned` for honorable-path slots. That is Personal Kanban's work-in-progress limit, moved from your attention span to your actual constraints, which are honorable-path capacity, model spend, and the fact that a human still has to review a hundred merges.

### Fit with your `C:\dev` conventions and GitHub

`_cards\` matches the underscore-prefixed meta-folder pattern, so it sits alongside `_meta`, `_scripts`, `_templates`, and `_archive` without looking foreign. The skill reads NAMING_CONVENTIONS.md and SESSION_PROTOCOL.md at runtime instead of assuming their contents, so it stays compatible with conventions I cannot see. The card template defers to your `_templates\` convention. Sweeping done cards into `_archive\` uses a folder you already have. The whole `_cards\` tree is version-controlled, every card and every move is a commit, and batch manifests in `_batches\` tie a cluster of cards back to the user story that spawned them. No database, no external service. The filesystem and git are the system, which is the only way the bookkeeping stays cheap enough to be worth it.

### Tradeoffs and open questions

The honest ones, because a proposal that only lists upsides is selling something.

Card granularity is the central risk and it never fully goes away. Too coarse and the cards are not actually parallel. Too fine and writing and tracking a hundred files costs more than the parallelism saves, which violates the one principle that justifies the whole system. The per-card size gate and the claimable-card-count metric are the defense, but sizing stays a judgment call, and it is the judgment call the multi-agent planning step exists to get right.

The whole thing only pays off above a threshold. If a user story decomposes into five cards, the manifest-and-folder overhead probably is not worth it and you should just do the work. A sensible heuristic: `/cards` earns its keep when the card count is high enough that real parallelism is on the table, or when the tier routing will save meaningful model spend. Below that, the skill should say so rather than dutifully generating five cards.

Manual estimation drifts. The research is clear that learned routers generalize better than human guesses, and your planner is guessing. The `model` versus `model_used` diff catches execution drift, but it does not catch planner mis-estimation. The open question is whether to log card outcomes (succeeded, failed, retried, escalated) lightly so the rubric can be tuned against reality. I would, eventually, but not in version one.

The tier table will rot as models change. This is contained, not solved: the table lives in exactly one place, the skill's rubric, and because cards store `stakes` and `difficulty` separately, old cards can be re-mapped by re-running the grid. When the model lineup changes you edit one table.

A few genuinely open items. Cross-project batches: the `project` field supports cards with different paths in one batch, but a discussion that spans projects is an untested workflow. Dependency deadlock: if a prerequisite card lands in `blocked\`, its dependents stall silently, so the next `/cards` run needs a `blocked\` triage step. Failure escalation: when a low-tier card fails its acceptance criteria, do you retry at the same tier or bump its points? I'd recommend manual re-triage through `blocked\` rather than an automatic cascade, because auto-cascades waste tokens, but it is a real choice. And the runner itself: this proposal specifies the card contract and the lifecycle, but the harness that polls `backlog\`, spawns an agent per card, and enforces the honorable-versus-advisory split is a separate companion piece. It could be a sibling `/run-cards` skill or a script in `_scripts\`. I'd lean toward a script, since polling and process management is not really a language-model job.

### Design choices, as options

**State representation.** Option A, folders only, the folder a card sits in is its entire state. Option B, folders plus a redundant `status` field that mirrors the folder. The independent design draft picked B for grep-ability and merge resilience. I recommend A. A mirror is a second source of truth, and a second source of truth is a thing that drifts. `ls active\` is your board, `git log` is your history, and an executing agent already knows the folder because it is reading a path. If you later find you genuinely need to query state without touching the filesystem, add the field then.

**How many planning agents.** Option A, a fixed crew of three (Decomposer, Estimator, Reviewer) every time. Option B, two by default (Planner, adversarial Reviewer) scaling to three for large or ambiguous stories. I recommend B. It matches your "an agent, or two agents" instinct, it keeps the cheap case cheap, and the adversarial Reviewer is the role that actually catches the expensive mistakes, so it is the one that should never be cut.

**Storing the axes.** Option A, store only `points`, `model`, and `extended_thinking`, since the axes were just an input to the decision. Option B, also store `stakes` and `difficulty`. I recommend B despite it being three extra one-word fields. It is what makes the assignment auditable, it is what lets you re-map old cards when the tier table changes, and the research's loudest warning is precisely that collapsing the two axes into one number is where mis-routing comes from. Keeping the axes visible underneath the point value is cheap insurance against the system's main known failure mode.

**Where `pin_required` comes from.** Option A, derive it from the point value, 5 and 6 are pinned. Option B, derive it from the stakes axis, high stakes is pinned. Same set of cards either way, but I recommend B because the reason matters: it is stakes, not difficulty, that makes a wrong model dangerous, and tying the flag to the axis keeps the logic honest if the tier table ever shifts.

---

A closing thought on the guiding principle, since it's the one that decides whether any of this gets built. The system is lean in the right places: no database, no service, the filesystem and git do the persistence, and the bookkeeping per card is a dozen frontmatter fields plus a five-section brief that the planner writes anyway as the natural output of decomposing the work. The cost that is not lean is the planning step, and that is deliberate. You are spending multi-agent opus time up front so that a hundred cheap, pinned, parallel agents can run without a human in the loop per card. That trade only clears if your stories are big enough to decompose wide. For small work, the right move is for `/cards` to tell you to just go do it.

Sources:

- [One man Scrum Team. Possible? (Scrum.org)](https://www.scrum.org/forum/scrum-forum/36139/one-man-scrum-team-possible)
- [How to Scrum for One-Man Operations (HackerNoon)](https://medium.com/hackernoon/how-to-scrum-for-one-man-operations-e8fc0dc5a58c)
- [Scrum for One (Lucidchart)](https://www.lucidchart.com/blog/scrum-for-one)
- [Scrum Solo considered harmful (SoftEd)](https://www.softed.com/news/scrum-solo-considered-harmful/)
- [Scrum Solo considered harmful (ProjectManagement.com)](https://www.projectmanagement.com/blog-post/13211/scrum-solo-considered-harmful)
- [What is Kanban (Personal Kanban)](https://personalkanban.com/learn/what-is-kanban/)
- [Working with WIP limits for Kanban (Atlassian)](https://www.atlassian.com/agile/kanban/wip-limits)
- [WIP limits in Personal Kanban (Flow-e)](https://flow-e.com/personal-kanban/wip/)
- [Agile estimation and story points (Atlassian)](https://www.atlassian.com/agile/project-management/estimation)
- [Agent Stories (Slava Kurilyak)](https://slavakurilyak.com/posts/agent-stories)
- [Spec-driven development with AI (GitHub Blog)](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/)
- [TASKS.md](https://tasksmd.github.io/tasks.md/)
- [taskmd: task management for the AI era](https://medium.com/@driangle/taskmd-task-management-for-the-ai-era-92d8b476e24e)
- [Breaking down tasks: task decomposition for AI agents](https://mbrenndoerfer.com/writing/breaking-down-tasks-task-decomposition-ai-agents)
- [IBM's Neel Sundaresan on wasting frontier models on trivial tasks](https://startupfortune.com/ibms-neel-sundaresan-says-most-ai-coding-wastes-frontier-models-on-trivial-tasks/)
- [Model routing engines for selecting the right model per request (PCStacks)](https://www.pcstacks.com/model-routing-engines-for-selecting-the-right-model-per-request/)
- [Big or Small LLMs (DataOps.live)](https://www.dataops.live/blog/big-or-small-llms)
- [Vibe Kanban](https://vibekanban.com/)
- [Kangentic](https://kangentic.com/)
- [Claw-Kanban (GitHub)](https://github.com/GreenSheep01201/Claw-Kanban)
- [agent-kanban (GitHub)](https://github.com/saltbo/agent-kanban)
- [RouteLLM (LMSYS)](https://lmsys.org/blog/2024-07-01-routellm/)
- [FrugalGPT (arXiv)](https://arxiv.org/pdf/2305.05176)
- [BEST-Route (Microsoft, GitHub)](https://github.com/microsoft/best-route-llm)
- [OpenRouter Auto Router](https://openrouter.ai/docs/guides/routing/routers/auto-router)
- [Awesome AI Model Routing (Not Diamond, GitHub)](https://github.com/Not-Diamond/awesome-ai-model-routing)
- [IBM Research on LLM routers](https://research.ibm.com/blog/LLM-routers)
- [Parallel agentic development with git worktrees (MindStudio)](https://www.mindstudio.ai/blog/parallel-agentic-development-git-worktrees)
- [Claude Squad: multiple AI agents in parallel](https://dev.to/stevengonsalvez/claude-squad-run-multiple-ai-agents-in-parallel-without-the-mess-1hfl)
- [opencode: dynamic model selection for subagents (GitHub issue)](https://github.com/anomalyco/opencode/issues/6651)
