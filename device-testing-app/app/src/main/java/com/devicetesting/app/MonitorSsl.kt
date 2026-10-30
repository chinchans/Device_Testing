package com.devicetesting.app

import android.content.Context
import java.io.BufferedInputStream
import java.net.HttpURLConnection
import java.security.KeyStore
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * AppSail uses Let's Encrypt Gen-Y (YR1 → Root YR → ISRG Root X1).
 * Old phones (Galaxy J5 / Android 6) often lack those roots in the system
 * trust store, so [HttpsURLConnection] fails while Chrome may still work.
 * Bundle the roots and merge them with the platform trust managers.
 */
object MonitorSsl {
    @Volatile
    private var socketFactory: SSLSocketFactory? = null

    private val rawRoots = intArrayOf(
        R.raw.isrg_root_x1,
        R.raw.isrg_root_x2,
        R.raw.isrg_root_yr,
        R.raw.isrg_root_yr_x1,
        R.raw.le_yr1,
    )

    fun apply(context: Context, conn: HttpURLConnection) {
        if (conn !is HttpsURLConnection) return
        conn.sslSocketFactory = factory(context.applicationContext)
    }

    private fun factory(context: Context): SSLSocketFactory {
        socketFactory?.let { return it }
        synchronized(this) {
            socketFactory?.let { return it }
            val built = buildFactory(context)
            socketFactory = built
            return built
        }
    }

    private fun buildFactory(context: Context): SSLSocketFactory {
        val cf = CertificateFactory.getInstance("X.509")
        val extras = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null, null) }
        var index = 0
        for (resId in rawRoots) {
            runCatching {
                context.resources.openRawResource(resId).use { raw ->
                    BufferedInputStream(raw).use { input ->
                        val cert = cf.generateCertificate(input)
                        extras.setCertificateEntry("le-extra-$index", cert)
                        index += 1
                    }
                }
            }
        }

        val defaultTmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        defaultTmf.init(null as KeyStore?)
        val extraTmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        extraTmf.init(extras)

        val managers = (
            defaultTmf.trustManagers.filterIsInstance<X509TrustManager>() +
                extraTmf.trustManagers.filterIsInstance<X509TrustManager>()
            )
        require(managers.isNotEmpty()) { "No X509 trust managers available" }

        val composite = object : X509TrustManager {
            override fun getAcceptedIssuers(): Array<X509Certificate> =
                managers.flatMap { it.acceptedIssuers.toList() }.toTypedArray()

            override fun checkClientTrusted(chain: Array<out X509Certificate>, authType: String) {
                checkWithAny(managers) { it.checkClientTrusted(chain, authType) }
            }

            override fun checkServerTrusted(chain: Array<out X509Certificate>, authType: String) {
                checkWithAny(managers) { it.checkServerTrusted(chain, authType) }
            }
        }

        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf<TrustManager>(composite), null)
        return ctx.socketFactory
    }

    private fun checkWithAny(
        managers: List<X509TrustManager>,
        check: (X509TrustManager) -> Unit,
    ) {
        var last: CertificateException? = null
        for (tm in managers) {
            try {
                check(tm)
                return
            } catch (e: CertificateException) {
                last = e
            }
        }
        throw last ?: CertificateException("Server certificate not trusted")
    }
}
