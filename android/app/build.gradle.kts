plugins {
    id("com.android.application")
}

// Release signing is driven by CI secrets / local env vars. All four are
// optional: when absent the release build is left unsigned (and the CI
// workflow falls back to the debug APK), so a plain `assembleDebug` on a
// fresh checkout keeps working with no keystore.
val envStoreFile: String? = System.getenv("URAI_KEYSTORE_FILE")
    ?: (project.findProperty("URAI_KEYSTORE_FILE") as String?)
val envStorePassword: String? = System.getenv("URAI_KEYSTORE_PASSWORD")
    ?: (project.findProperty("URAI_KEYSTORE_PASSWORD") as String?)
val envKeyAlias: String? = System.getenv("URAI_KEY_ALIAS")
    ?: (project.findProperty("URAI_KEY_ALIAS") as String?)
val envKeyPassword: String? = System.getenv("URAI_KEY_PASSWORD")
    ?: (project.findProperty("URAI_KEY_PASSWORD") as String?)

val releaseKeystore: File? = envStoreFile
    ?.takeIf { it.isNotBlank() }
    ?.let { file(it) }
    ?.takeIf { it.exists() }

val hasReleaseSigning: Boolean = releaseKeystore != null
    && !envStorePassword.isNullOrBlank()
    && !envKeyAlias.isNullOrBlank()
    && !envKeyPassword.isNullOrBlank()

android {
    namespace = "io.github.tukitattu.urai"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.tukitattu.urai"
        minSdk = 24
        targetSdk = 34
        // CI passes the release tag through as URAI_VERSION_NAME / _CODE; a
        // plain local build keeps the 1.0 / 1 defaults.
        versionCode = (System.getenv("URAI_VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("URAI_VERSION_NAME") ?: "1.0"
    }

    signingConfigs {
        create("release") {
            if (hasReleaseSigning) {
                storeFile = releaseKeystore
                storePassword = envStorePassword
                keyAlias = envKeyAlias
                keyPassword = envKeyPassword
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        getByName("debug") {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }
}

// Project-scope dependencies (was previously misplaced inside android { }).
dependencies {
    implementation("androidx.core:core:1.13.1")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
}
