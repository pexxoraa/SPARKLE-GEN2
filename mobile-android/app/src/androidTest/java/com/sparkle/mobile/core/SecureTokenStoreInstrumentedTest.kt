package com.sparkle.mobile.core

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.sparkle.mobile.Enrollment
import com.sparkle.mobile.SecureTokenStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureTokenStoreInstrumentedTest {
    private lateinit var context: Context
    private lateinit var store: SecureTokenStore

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        store = SecureTokenStore(context)
        store.clear()
    }

    @Test
    fun credential_round_trip_and_complete_identity_verification() {
        val expected = Enrollment(
            token = "test-device-token",
            deviceId = "device-1",
            name = "Phone",
            kind = "android",
            osName = "Android",
            sessionId = "session-1",
        )

        assertTrue(store.save(expected))
        assertEquals(expected, store.load())
    }

    @Test
    fun clear_removes_complete_local_pairing_identity() {
        val value = Enrollment("token", "device", "Phone", "android", "Android")
        assertTrue(store.save(value))
        store.clear()
        assertNull(store.load())
    }

    @Test
    fun incomplete_persisted_identity_is_rejected() {
        context.getSharedPreferences("sparkle_auth", Context.MODE_PRIVATE)
            .edit()
            .putString("device_id", "device-only")
            .commit()

        assertNull(store.load())
    }
}
