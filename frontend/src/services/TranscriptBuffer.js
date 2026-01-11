/**
 * TranscriptBuffer - Manages transcript buffering with regex intent detection
 * and rate-limited Groq (OpenAI-compatible) calls for task extraction
 */

// LLM API configuration (defaults keep backward compatibility)
const GROQ_API_KEY = import.meta.env.VITE_GROQ_API_KEY || import.meta.env.VITE_GEMINI_API_KEY;
const GROQ_MODEL = import.meta.env.VITE_GROQ_MODEL || "openai/gpt-oss-120b";
const GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";

// Minimum time between Groq calls (30 seconds to avoid rate limiting)
const MIN_CALL_INTERVAL_MS = 30 * 1000;
const ISO_DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;
const WEEKDAY_INDEX = {
    sunday: 0,
    monday: 1,
    tuesday: 2,
    wednesday: 3,
    thursday: 4,
    friday: 5,
    saturday: 6,
};

const toIsoDateString = (value) => {
    try {
        const date = value instanceof Date ? new Date(value.getTime()) : new Date(value);
        if (Number.isNaN(date.getTime())) {
            return null;
        }
        return date.toISOString().split('T')[0];
    } catch {
        return null;
    }
};

const addDays = (date, days) => {
    const result = new Date(date.getTime());
    result.setDate(result.getDate() + days);
    return result;
};

const resolveRelativeWeekday = (text, referenceDate) => {
    const match = text.match(/^(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$/);
    if (!match) return null;
    const isNext = Boolean(match[1]);
    const dayName = match[2];
    const targetIndex = WEEKDAY_INDEX[dayName];
    if (typeof targetIndex !== 'number') return null;

    const refIndex = referenceDate.getDay();
    let delta = (targetIndex - refIndex + 7) % 7;
    if (delta === 0 && (isNext || text.startsWith('next'))) {
        delta = 7;
    }
    if (isNext && delta <= 0) {
        delta += 7;
    }
    if (delta === 0) {
        return toIsoDateString(referenceDate);
    }
    return toIsoDateString(addDays(referenceDate, delta));
};

const normalizeDeadlineValue = (input, referenceDate = new Date()) => {
    if (input === null || input === undefined) return null;
    const text = String(input).trim();
    if (!text) return null;

    const lower = text.toLowerCase();
    if (['not specified', 'unspecified', 'none', 'n/a'].includes(lower)) {
        return null;
    }

    if (ISO_DATE_REGEX.test(text)) {
        return text;
    }

    const parsed = toIsoDateString(text);
    if (parsed) {
        return parsed;
    }

    const relativeMap = {
        today: 0,
        tomorrow: 1,
        yesterday: -1,
    };
    if (relativeMap.hasOwnProperty(lower)) {
        return toIsoDateString(addDays(referenceDate, relativeMap[lower]));
    }

    if (lower === 'next week') {
        return toIsoDateString(addDays(referenceDate, 7));
    }

    if (lower === 'end of week') {
        const refDow = referenceDate.getDay();
        let delta = (5 - refDow + 7) % 7;
        if (delta <= 0) delta += 7;
        return toIsoDateString(addDays(referenceDate, delta));
    }

    if (lower === 'end of next week') {
        const refDow = referenceDate.getDay();
        let delta = (5 - refDow + 7) % 7;
        if (delta <= 0) delta += 7;
        delta += 7;
        return toIsoDateString(addDays(referenceDate, delta));
    }

    const weekdayIso = resolveRelativeWeekday(lower, referenceDate);
    if (weekdayIso) {
        return weekdayIso;
    }

    return null;
};

const normalizeTaskDeadlines = (tasks = [], referenceDate = new Date()) => (
    tasks.map((task) => ({
        ...task,
        deadline: normalizeDeadlineValue(task.deadline, referenceDate),
    }))
);

// ============================================
// REGEX PATTERNS FOR INTENT DETECTION
// ============================================

// Simple action verbs
const ACTION_VERBS = /\b(need|should|will|must|please|let's|can|could|do|make|send|check|update|review|call|email|work|task|handle|finish|complete)\b/i;

// Simple responsibility/assignment 
const RESPONSIBILITY_PHRASES = /\b(you|your|I'll|I will|we|someone|team|@\w+)\b/i;

// Time words
const TIME_URGENCY = /\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|soon|asap|urgent|deadline|week|day|morning|afternoon|evening)\b/i;

// Strong patterns 
const STRONG_ACTION_PATTERNS = /\b(action|todo|task|follow.?up|next step|milestone|deliverable|homework|meeting|project)\b/i;

// ============================================
// TRANSCRIPT BUFFER CLASS
// ============================================

class TranscriptBuffer {
    constructor() {
        this.buffer = []; // Array of { text: string, timestamp: number }
        this.lastLLMCallAt = 0;
        this.regexHitSinceLastCall = false;
        this.isCallingGemini = false; // Legacy field name retained for compatibility
    }

    /**
     * Add a final transcript to the buffer and check for intent patterns
     * @param {string} text - The transcript text
     * @returns {boolean} - Whether regex patterns were detected
     */
    addTranscript(text) {
        if (!text || text.trim() === "") return false;

        // Store the transcript
        this.buffer.push({
            text: text.trim(),
            timestamp: Date.now()
        });

        console.log(`[Buffer] Added transcript: "${text.trim().substring(0, 50)}..." (Total: ${this.buffer.length})`);

        // Check regex patterns
        const hasIntentMatch = this.checkIntentPatterns(text);

        if (hasIntentMatch) {
            this.regexHitSinceLastCall = true;
            console.log("[Buffer] ✓ Regex intent detected!");
        }

        return hasIntentMatch;
    }

    /**
     * Check if text matches intent patterns
     * @param {string} text - Text to check
     * @returns {boolean} - Whether intent patterns were detected
     */
    checkIntentPatterns(text) {
        // Check strong action patterns first (these alone are enough)
        if (STRONG_ACTION_PATTERNS.test(text)) {
            console.log("[Regex] ✓ Strong action pattern matched");
            return true;
        }

        // Count how many pattern groups match
        let matchedGroups = 0;

        if (ACTION_VERBS.test(text)) {
            matchedGroups++;
            console.log("[Regex] ✓ Action verb matched");
        }

        if (RESPONSIBILITY_PHRASES.test(text)) {
            matchedGroups++;
            console.log("[Regex] ✓ Responsibility phrase matched");
        }

        if (TIME_URGENCY.test(text)) {
            matchedGroups++;
            console.log("[Regex] ✓ Time/urgency matched");
        }

        // RELAXED: Trigger if just 1 group matches (for testing)
        return matchedGroups >= 1;
    }

    /**
     * Check if conditions are met for calling the Groq LLM (legacy method name)
     * @returns {{ canCall: boolean, reason: string }}
     */
    checkGeminiConditions() {
        const now = Date.now();
        const timeSinceLastCall = now - this.lastLLMCallAt;
        const hasEnoughTime = timeSinceLastCall >= MIN_CALL_INTERVAL_MS;

        if (this.isCallingGemini) {
            return { canCall: false, reason: "Groq call already in progress" };
        }

        if (!this.regexHitSinceLastCall) {
            return { canCall: false, reason: "No regex intent detected since last call" };
        }

        if (!hasEnoughTime) {
            const remaining = Math.ceil((MIN_CALL_INTERVAL_MS - timeSinceLastCall) / 1000);
            return { canCall: false, reason: `Time gate: ${remaining}s remaining` };
        }

        if (this.buffer.length === 0) {
            return { canCall: false, reason: "Buffer is empty" };
        }

        return { canCall: true, reason: "All conditions met" };
    }

    /**
     * Get all buffered transcripts as a single text
     * @returns {string}
     */
    getBufferedText() {
        return this.buffer.map(entry => entry.text).join(" ");
    }

    /**
     * Call Groq to extract task candidates (legacy method name kept for compatibility)
     * @returns {Promise<Object|null>}
     */
    async callGemini() {
        const conditions = this.checkGeminiConditions();

        if (!conditions.canCall) {
            console.log(`[Groq] Skipping: ${conditions.reason}`);
            return null;
        }

        if (!GROQ_API_KEY) {
            console.error("[Groq] VITE_GROQ_API_KEY is not set");
            return null;
        }

        this.isCallingGemini = true;
        const transcriptText = this.getBufferedText();
        const transcriptCount = this.buffer.length;
        const referenceTimestamp = this.buffer.length ? this.buffer[this.buffer.length - 1].timestamp : Date.now();
        const referenceDate = new Date(referenceTimestamp);
        const meetingDateIso = toIsoDateString(referenceDate) || toIsoDateString(new Date());

        console.log(`%c[Groq] 🚀 Calling with ${transcriptCount} transcripts (${transcriptText.length} chars)`, "font-weight: bold; color: #fbbf24;");

        const systemPrompt = "You are a meeting assistant that extracts actionable tasks from meeting transcripts.";
        const userPrompt = `Analyze the following meeting transcript and extract any tasks, action items, or assignments mentioned.

TRANSCRIPT:
"""
${transcriptText}
"""

Use ${meetingDateIso || 'the current date'} as the meeting date when resolving phrases like "tomorrow" or "next Friday". Always convert relative references into absolute calendar dates.

Extract tasks in the following STRICT JSON format. Return ONLY valid JSON, no markdown or explanations:

{
  "tasks": [
    {
      "title": "Brief task title",
      "description": "Detailed description of what needs to be done",
      "assignee": "Person responsible (or 'Unassigned' if not clear)",
      "priority": "high" | "medium" | "low",
      "deadline": "YYYY-MM-DD" | null,
      "confidence": 0.0-1.0
    }
  ],
  "summary": "Brief summary of the meeting segment"
}

If no clear tasks are found, return: {"tasks": [], "summary": "No clear tasks identified"}`;

        try {
            const response = await fetch(GROQ_API_URL, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${GROQ_API_KEY}`
                },
                body: JSON.stringify({
                    model: GROQ_MODEL,
                    messages: [
                        { role: "system", content: systemPrompt },
                        { role: "user", content: userPrompt }
                    ],
                    temperature: 0.2,
                    top_p: 0.8,
                    max_tokens: 1024
                })
            });

            if (!response.ok) {
                throw new Error(`Groq API error: ${response.status}`);
            }

            const data = await response.json();
            const messageContent = data?.choices?.[0]?.message?.content;
            let textResponse = "";
            if (Array.isArray(messageContent)) {
                textResponse = messageContent
                    .map(part => (typeof part === "string" ? part : part?.text || ""))
                    .join(" ")
                    .trim();
            } else if (typeof messageContent === "string") {
                textResponse = messageContent;
            } else if (messageContent && typeof messageContent === "object") {
                textResponse = messageContent?.text || "";
            }

            // Parse JSON from response
            let result;
            try {
                // Strip markdown code blocks if present
                let cleanedResponse = textResponse;
                if (cleanedResponse.includes("```json")) {
                    cleanedResponse = cleanedResponse.replace(/```json\s*/g, "").replace(/```\s*/g, "");
                } else if (cleanedResponse.includes("```")) {
                    cleanedResponse = cleanedResponse.replace(/```\s*/g, "");
                }

                // Try to extract JSON from the response
                const jsonMatch = cleanedResponse.match(/\{[\s\S]*\}/);
                if (jsonMatch) {
                    try {
                        result = JSON.parse(jsonMatch[0]);
                    } catch (innerError) {
                        // If JSON is truncated, try to fix it
                        console.warn("[Groq] JSON appears truncated, attempting repair...");
                        const fixedJson = jsonMatch[0];

                        // First, try to find the last complete task and truncate there
                        const taskPattern = /\{\s*"title"\s*:\s*"[^"]*"\s*,\s*"description"\s*:\s*"[^"]*"\s*,\s*"assignee"\s*:\s*"[^"]*"\s*,\s*"priority"\s*:\s*"[^"]*"\s*,\s*"deadline"\s*:\s*"[^"]*"\s*,\s*"confidence"\s*:\s*[\d.]+\s*\}/g;
                        const completeTasks = fixedJson.match(taskPattern);

                        if (completeTasks && completeTasks.length > 0) {
                            // Reconstruct with only complete tasks
                            result = {
                                tasks: completeTasks.map(taskStr => JSON.parse(taskStr)),
                                summary: "Partial response - some tasks may be missing"
                            };
                            console.log(`[Groq] Recovered ${completeTasks.length} complete task(s) from truncated response`);
                        } else {
                            throw innerError;
                        }
                    }
                } else {
                    throw new Error("No JSON found in response");
                }
            } catch (parseError) {
                console.error("[Groq] Failed to parse response:", parseError);
                console.log("[Groq] Raw response:", textResponse.substring(0, 500) + "...");
                result = { tasks: [], summary: "Failed to parse response", error: parseError.message };
            }

            // Normalize deadlines to ISO format
            if (result && Array.isArray(result.tasks)) {
                result.tasks = normalizeTaskDeadlines(result.tasks, referenceDate);
            }

            // Log the structured task candidates
            console.log("%c[Groq] ✅ Task Candidates:", "font-weight: bold; color: #4ade80;");
            console.log(JSON.stringify(result, null, 2));

            if (result.tasks && result.tasks.length > 0) {
                result.tasks.forEach((task, i) => {
                    console.log(`%c  📋 Task ${i + 1}: ${task.title}`, "font-weight: bold; color: #60a5fa;");
                    console.log(`    Assignee: ${task.assignee}`);
                    console.log(`    Priority: ${task.priority}`);
                    console.log(`    Deadline: ${task.deadline}`);
                    console.log(`    Confidence: ${(task.confidence * 100).toFixed(0)}%`);
                });
            } else {
                console.log("  No tasks detected in this segment");
            }

            // Reset state after successful call
            this.lastLLMCallAt = Date.now();
            this.regexHitSinceLastCall = false;
            this.buffer = [];
            this.isCallingGemini = false;

            console.log("[Buffer] State reset after Groq call");

            return result;

        } catch (error) {
            console.error("[Groq] API call failed:", error);

            // IMPORTANT: Set lastLLMCallAt on failure too, to prevent immediate retry loop
            // Add extra cooldown on failure (exponential backoff)
            const backoffMs = error.message?.includes('429') ? 60000 : 30000; // 60s for rate limit, 30s for other errors
            this.lastLLMCallAt = Date.now() + backoffMs - MIN_CALL_INTERVAL_MS; // Effectively add backoff time
            this.isCallingGemini = false;

            console.log(`[Groq] Backing off for ${backoffMs / 1000}s after error`);
            return null;
        }
    }

    /**
     * Force check and potentially call Groq (legacy name kept)
     * @returns {Promise<Object|null>}
     */
    async tryCallGemini() {
        return await this.callGemini();
    }

    /**
     * Get buffer stats for debugging
     * @returns {Object}
     */
    getStats() {
        const now = Date.now();
        const timeSinceLastCall = now - this.lastLLMCallAt;
        const timeUntilNextCall = Math.max(0, MIN_CALL_INTERVAL_MS - timeSinceLastCall);

        return {
            bufferSize: this.buffer.length,
            totalChars: this.getBufferedText().length,
            regexHitSinceLastCall: this.regexHitSinceLastCall,
            timeSinceLastCall: Math.floor(timeSinceLastCall / 1000),
            timeUntilNextCall: Math.ceil(timeUntilNextCall / 1000),
            canCallGemini: this.checkGeminiConditions().canCall
        };
    }

    /**
     * Clear the buffer without calling Groq
     */
    clear() {
        this.buffer = [];
        this.regexHitSinceLastCall = false;
        console.log("[Buffer] Cleared");
    }
}

// Export singleton instance
export const transcriptBuffer = new TranscriptBuffer();
export default TranscriptBuffer;