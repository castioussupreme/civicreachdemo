# Engineering Case Study

# **🤖 AI Eligibility Agent for Social Services**

## **Overview**

You are building a proof-of-concept text-based AI agent that helps a resident determine whether they likely qualify for a public benefits program. We'll use NC FNS (North Carolina’s SNAP food-assistance program) as our example, but you are welcome to pick any comparable program with public eligibility rules. The agent should hold a natural, multi-turn conversation with the user, ask the questions it needs, ground its answers in a small knowledge base of public eligibility documents, and return a useful, honest assessment.

<aside>

🔔 Note - we reference CalFresh and other public programs as examples only. Please do not build anything that submits real applications, contacts a real agency, or scrapes any government system. Use only public eligibility documents you assemble yourself.

</aside>

**What we're testing:** We want to see four things at this stage: (1) architectural judgment for AI agent design, (2) guardrail thinking, (3) failure-mode reasoning, and (4) reasoning about tradeoffs. We care much more about how you think through these than about volume of features shipped.

**Our expectations:**

- You spend ~20 hours working on this case study
- We pay you $200 to start the case study (_to cover any/all development/LLM costs_)
- We pay you $800 after submitting a case study solution (_to compensate you for your time_)
- **You submit your solution and attend a review meeting 7 days after beginning** (after receiving this case study)
- We strongly prefer **smaller scope done well over broad scope half-baked**. 15-20 hours is short on purpose: it should force you to make meaningful tradeoffs about what a demo-quality agent needs. Tell us what you cut and why.

**At a high level, the agent must:**

1. **Hold a multi-turn text conversation** with a user who wants to know if they qualify for the program.
2. **Ground its answers in a knowledge base** of public eligibility documents (RAG, embeddings, or any retrieval approach you prefer) rather than relying on the model's parametric memory.
3. **Use tools / structured logic** where appropriate (e.g., an eligibility calculation, income thresholds, household-size lookups) instead of hand-waving the rules.
4. **Track conversation state** across turns - remembering what the user has already told it and asking only for what it still needs.

**You'll impress us, if the agent can:**

1. **Handle guardrails gracefully** - refusals for out-of-scope asks, crisis escalation if a user discloses distress, and sensible handling of PII.
2. **Survive adversarial and messy input** - prompt-injection attempts ("ignore previous instructions"), ambiguous answers ("I make about $2,500/month"), off-topic detours, and self-contradictions across turns.

---

## **How to Submit**

1. **GitHub Repo Link**: Provide us with a link to your repository (public or private; if private, please invite us).
2. **Instructions/README**: A clear description, overview, and set of steps for how we can run and test your agent locally.
3. **Runnable Agent**: A way for us to interact with your agent (CLI, simple web UI, notebook — your call). It must be something we can drive live in the review meeting.
4. **Review Meeting**: Schedule a meeting to review your work / solution. This meeting / your deadline is 10-14 days after beginning (after receiving this case study). **Heads-up: this meeting is interactive — see below. Come prepared to run your agent live on inputs you haven't seen in advance.**

   📆 **Schedule Link**: https://app.reclaim.ai/m/civicreach/civicreach-eng-case-study-review

---

## **Final Note**

We **do not** expect a fully production-ready system in 15-20 hours — this is a proof-of-concept. We're primarily looking at how you think about agent architecture, guardrails, failure modes, and tradeoffs from end to end.

If you find yourself running out of time, it's better to deliver a well-structured partial solution _with clear documentation of what you'd do next_ than a messy or broken "feature-complete" one. Smaller scope done well beats broad scope half-baked, every time.

---

**Good luck, and have fun!** We're excited to see how you approach building a grounded, guarded AI agent for social services.
