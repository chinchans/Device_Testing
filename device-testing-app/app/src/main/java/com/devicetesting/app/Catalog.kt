package com.devicetesting.app

import android.content.Context
import org.json.JSONObject

data class TestCase(
    val id: String,
    val title: String,
    val suite: String,
    val execution: String,
)

object Catalog {
    val suiteOrder = listOf("functionality", "performance", "reliability", "security")

    fun suiteLabel(id: String) = when (id) {
        "functionality" -> "Functionality"
        "performance" -> "Performance"
        "reliability" -> "Reliability"
        "security" -> "Security"
        else -> id
    }

    fun load(context: Context): List<TestCase> {
        val text = context.assets.open("camera/catalog.json").bufferedReader().use { it.readText() }
        val categories = JSONObject(text).getJSONObject("categories")
        val cases = mutableListOf<TestCase>()
        for (suite in suiteOrder) {
            val list = categories.optJSONArray(suite) ?: continue
            for (i in 0 until list.length()) {
                val item = list.getJSONObject(i)
                cases += TestCase(
                    id = item.getString("id"),
                    title = item.getString("title"),
                    suite = suite,
                    execution = item.optString("execution", "AUTO"),
                )
            }
        }
        return cases
    }
}
