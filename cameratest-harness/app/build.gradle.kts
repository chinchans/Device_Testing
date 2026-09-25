plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.example.cameratest"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.cameratest"
        minSdk = 30
        targetSdk = 34
        versionCode = 10200
        versionName = "1.2.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // Self-instrumenting harness: runner lives in the same APK.
        testApplicationId = "com.example.cameratest"
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    // Operation classes live under src/main so assembleDebug packs them.
    sourceSets {
        getByName("main") {
            java.srcDirs("src/main/kotlin")
        }
    }
}

dependencies {
    // Packaged into the main APK so AndroidJUnitRunner can load the tests.
    implementation("androidx.test:runner:1.6.2")
    implementation("androidx.test:rules:1.6.1")
    implementation("androidx.test.ext:junit:1.2.1")
    implementation("androidx.annotation:annotation:1.8.2")
    implementation("junit:junit:4.13.2")
}
