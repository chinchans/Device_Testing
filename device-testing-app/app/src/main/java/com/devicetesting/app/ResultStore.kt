package com.devicetesting.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class CaseResult(
    val id: String,
    val title: String,
    val suite: String,
    val verdict: String,
    val detail: String,
    val media: List<String> = emptyList(),
)

data class RunRecord(
    val label: String,
    val finishedAt: Long,
    val results: List<CaseResult>,
) {
    fun count(verdict: String) = results.count { it.verdict == verdict }
}

class ResultStore(context: Context) {
    private val file = context.applicationContext.filesDir.resolve("last_run.json")
    var last: RunRecord? = null
        private set

    init {
        if (file.exists()) {
            try {
                last = decode(JSONObject(file.readText()))
            } catch (_: Exception) {
            }
        }
    }

    fun save(record: RunRecord) {
        last = record
        file.writeText(encode(record).toString())
    }

    fun verdictFor(id: String): String? = last?.results?.firstOrNull { it.id == id }?.verdict

    fun resultFor(id: String): CaseResult? = last?.results?.firstOrNull { it.id == id }

    private fun encode(record: RunRecord): JSONObject {
        val results = JSONArray()
        record.results.forEach { r ->
            results.put(
                JSONObject()
                    .put("id", r.id)
                    .put("title", r.title)
                    .put("suite", r.suite)
                    .put("verdict", r.verdict)
                    .put("detail", r.detail)
                    .put("media", JSONArray(r.media)),
            )
        }
        return JSONObject()
            .put("label", record.label)
            .put("finishedAt", record.finishedAt)
            .put("results", results)
    }

    private fun decode(obj: JSONObject): RunRecord {
        val arr = obj.getJSONArray("results")
        val results = (0 until arr.length()).map { i ->
            val item = arr.getJSONObject(i)
            val mediaJson = item.optJSONArray("media")
            val media = if (mediaJson == null) {
                emptyList()
            } else {
                (0 until mediaJson.length()).map { mediaJson.getString(it) }
            }
            CaseResult(
                id = item.getString("id"),
                title = item.getString("title"),
                suite = item.getString("suite"),
                verdict = item.getString("verdict"),
                detail = item.optString("detail"),
                media = media,
            )
        }
        return RunRecord(obj.optString("label"), obj.optLong("finishedAt"), results)
    }
}
