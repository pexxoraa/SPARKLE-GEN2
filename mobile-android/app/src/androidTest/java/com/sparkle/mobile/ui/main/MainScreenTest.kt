package com.sparkle.mobile.ui.main

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.sparkle.mobile.MainActivity
import com.sparkle.mobile.R
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainScreenTest {
    @Test
    fun pairing_and_core_controls_are_present() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertNotNull(activity.findViewById(R.id.core_url_input))
                assertNotNull(activity.findViewById(R.id.device_name_input))
                assertNotNull(activity.findViewById(R.id.pair_code_input))
                assertNotNull(activity.findViewById(R.id.test_core_button))
                assertNotNull(activity.findViewById(R.id.pair_button))
            }
        }
    }
}
