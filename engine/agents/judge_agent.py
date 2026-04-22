"""Judge agent — arbitrates when specialist agents disagree."""

import json
import os

import anthropic

JUDGE_TOOL = {
    "name": "submit_judgment",
    "description": "Submit the final arbitration decision for a disputed maintenance plan item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "final_action": {
                "type": "string",
                "enum": ["keep", "split", "merge", "reclassify"],
                "description": "The final recommended action.",
            },
            "winning_agent": {
                "type": "string",
                "enum": ["safety", "cost", "efficiency", "integrity", "compromise"],
                "description": "Which agent's perspective drove the decision, or 'compromise'.",
            },
            "judge_rationale": {
                "type": "string",
                "description": "Clear explanation (3–5 sentences) of why this decision was made, referencing specific agent concerns.",
            },
            "modified": {
                "type": "boolean",
                "description": "True if the final action differs from what the majority (or any) specialist recommended.",
            },
        },
        "required": ["final_action", "winning_agent", "judge_rationale", "modified"],
    },
}


class JudgeAgent:
    """Arbitrates disagreements between specialist agents."""

    def __init__(self, profile):
        self.profile = profile
        self._client = None

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def adjudicate(self, item, decisions) -> dict:
        """
        Arbitrate between specialist agent decisions.

        Args:
            item: MaintenancePlanItem
            decisions: list of dicts from specialist agents
        Returns:
            dict with final_action, winning_agent, judge_rationale, modified
        """
        weights = {}
        try:
            if self.profile.scoring_weights:
                weights = json.loads(self.profile.scoring_weights)
        except Exception:
            weights = {
                "safety_weight": 0.35,
                "cost_weight": 0.20,
                "efficiency_weight": 0.20,
                "integrity_weight": 0.25,
            }

        agent_summaries = "\n".join(
            f"  [{d['agent_role'].upper()}] Score: {d.get('score', 0):.1f}/10 | "
            f"Action: {d.get('recommended_action', 'keep')} | "
            f"Confidence: {d.get('confidence', 'low')} | "
            f"Rationale: {d.get('rationale', '')[:200]}"
            for d in decisions
        )

        prompt = f"""The following specialist agents have reviewed a maintenance plan item and DISAGREE on the recommended action.

PLAN ITEM: {item.description or item.id}
  Frequency: {item.frequency} {item.frequency_unit}
  Online: {item.is_online} | Regulatory: {item.is_regulatory}
  Total Duration: {item.total_duration_hours:.1f}h

SPECIALIST AGENT REVIEWS:
{agent_summaries}

ARBITRATION WEIGHTS:
  Safety: {weights.get('safety_weight', 0.35):.0%}
  Integrity: {weights.get('integrity_weight', 0.25):.0%}
  Efficiency: {weights.get('efficiency_weight', 0.20):.0%}
  Cost: {weights.get('cost_weight', 0.20):.0%}

Make the final decision. Remember: safety and integrity concerns override cost/efficiency unless the concerns are minor.
Submit your judgment using the submit_judgment tool."""

        client = self._get_client()
        try:
            response = client.messages.create(
                model=self.profile.model_id or "claude-sonnet-4-6",
                max_tokens=1000,
                system=self.profile.system_prompt or "",
                messages=[{"role": "user", "content": prompt}],
                tools=[JUDGE_TOOL],
                tool_choice={"type": "any"},
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "submit_judgment":
                    return block.input

        except Exception as e:
            pass

        # Fallback: weight-averaged decision
        action_votes = {}
        for d in decisions:
            action = d.get("recommended_action", "keep")
            weight = weights.get(f"{d['agent_role']}_weight", 0.25)
            action_votes[action] = action_votes.get(action, 0) + weight

        best_action = max(action_votes, key=action_votes.get)
        return {
            "final_action": best_action,
            "winning_agent": "compromise",
            "judge_rationale": "Weighted vote applied due to judge agent error.",
            "modified": False,
        }
