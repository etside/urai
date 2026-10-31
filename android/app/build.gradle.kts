plugins {
    id("com.android.application")
}

android {
    namespace = "io.github.tukitattu.urai"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.tukitattu.urai"
        minSdk = 24
        targetSdk = 34
        versionCode = 111
        versionName = "1.1.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    dependencies {
        implementation("androidx.core:core:1.13.1")
    }
}
