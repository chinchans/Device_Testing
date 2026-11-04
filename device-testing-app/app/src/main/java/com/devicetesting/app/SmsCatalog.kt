package com.devicetesting.app

import android.content.Context
import org.json.JSONObject

/**
 * Field SMS cases that a normal Airtel SIM can run.
 * Lab, roaming, band-move, captive Wi-Fi, and emergency rows are not in this list.
 */
object SmsCatalog {
    fun load(context: Context): List<TestCase> {
        val text = context.assets.open(ASSET).bufferedReader().use { it.readText() }
        val list = JSONObject(text).getJSONArray("test_cases")
        val cases = mutableListOf<TestCase>()
        for (i in 0 until list.length()) {
            val meta = list.getJSONObject(i).getJSONObject("test_metadata")
            cases += TestCase(
                id = meta.getString("testCaseId"),
                title = meta.getString("title"),
                suite = meta.optString("suite", "functionality"),
                execution = meta.optString("execution_mode", "SEMI_AUTOMATED"),
                action = meta.optString("app_action"),
                radio = meta.optString("radio"),
            )
        }
        return cases
    }

    fun needsSavedNumber(test: TestCase): Boolean = test.action != "check_sms_setting"

    fun isVoWifi(test: TestCase): Boolean = test.radio == "VoWiFi"

    private const val ASSET = "sms/fut_sms_airtel_cases.json"
}
